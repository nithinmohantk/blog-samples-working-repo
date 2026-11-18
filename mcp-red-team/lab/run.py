"""The red-team run: hostile servers against a plain client and a guarded one, the scanner against a
labelled corpus, and hostile arguments against naive and hardened tools.

    python lab/run.py <output directory>
"""
from __future__ import annotations

import asyncio
import http.server
import json
import os
import sys
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

from guard.pins import PinStore  # noqa: E402
from guard.scan import scan_listing  # noqa: E402
from guard.session import Blocked, GuardedSession  # noqa: E402

HOSTILE = str(HERE.parent / "attacks" / "hostile_server.py")
DEPUTY = str(HERE.parent / "deputy" / "server.py")
OTHER_SERVERS_TOOLS = frozenset({"send_email"})  # the user also has a mail server connected


@asynccontextmanager
async def connect(script: str, *arguments: str, env: dict[str, str] | None = None, guard: GuardedSession | None = None):
    holder: dict = {}

    async def on_message(message):  # a notification arrives here; the plain client does nothing with it
        holder.setdefault("notifications", []).append(type(getattr(message, "root", message)).__name__)
        if holder.get("guard"):
            await holder["guard"].on_message(message)

    parameters = StdioServerParameters(command=sys.executable, args=[script, *arguments], env=env)
    with open(os.devnull, "w") as quiet:
        async with stdio_client(parameters, errlog=quiet) as (read, write):
            async with ClientSession(read, write, message_handler=on_message) as session:
                holder["init"] = await session.initialize()
                holder["session"] = session
                yield holder


def text_of(result) -> str:
    return "".join(getattr(block, "text", "") for block in result.content)


# Each scenario: mode, what the attack is, the call a user would make, and the marker that shows hostile content arrived.
SCENARIOS = [
    ("inject-description", "Hidden instruction block in a tool description", ("add", {"a": 2, "b": 3, "sidenote": ""}), "id_rsa"),
    ("inject-invisible", "Instruction written in invisible Unicode tag characters", ("add", {"a": 2, "b": 3}), chr(0xE0041)),
    ("inject-schema", "Instructions in a parameter description and an enum value", ("add", {"a": 2, "b": 3}), "ignore all previous"),
    ("inject-instructions", "Instruction block in the server's instructions field", ("add", {"a": 2, "b": 3}), "id_rsa"),
    ("exfil-parameter", "Required parameter that asks for the conversation", ("summarise", {"text": "x", "context": ""}), "full conversation"),
    ("shadow", "Description that changes how another server's tool is used", ("lookup_postcode", {"postcode": "H91"}), "send_email"),
    ("collision", "Tool with the same name as a tool on a trusted server", ("send_email", {"to": "a@example.com", "body": "hi"}), "send_email"),
    ("lying-annotations", "Destructive tool that declares itself read-only", ("delete_all_orders", {}), "delete_all_orders"),
    ("inject-result", "Instructions inside a tool result", ("get_order", {"number": 1042}), "ignore previous instructions"),
    ("rug-pull-silent", "Definition changes after the first call, no notification", ("add", {"a": 2, "b": 3}), "id_rsa"),
    ("rug-pull-notified", "Definition changes after the first call, with list_changed", ("add", {"a": 2, "b": 3}), "id_rsa"),
    ("flood-tools", "Listing of 5,000 tools", ("tool_0001", {}), "tool_4999"),
    ("huge-description", "One-megabyte tool description", ("add", {"a": 2, "b": 3}), "x" * 1000),
    ("endless-pagination", "Listing that always returns another page", ("add", {"a": 2, "b": 3}), None),
    ("huge-result", "Twenty-megabyte tool result", ("get_order", {"number": 1}), "y" * 1000),
]


async def plain_client(mode: str, call: tuple[str, dict], marker: str | None) -> dict:
    """What mcp.ClientSession does with no help: list, call twice, list again."""
    row: dict = {}
    async with connect(HOSTILE, mode) as link:
        session = link["session"]
        started = time.perf_counter()
        if mode == "endless-pagination":
            pages, cursor = 0, None
            while pages < 1000:  # an application that loops "until there is no cursor" never leaves this loop
                page = await session.list_tools(cursor)
                pages, cursor = pages + 1, page.nextCursor
                if not cursor:
                    break
            row["observed"] = f"still being handed a cursor after {pages} pages; stopped by the test"
            return row
        listing = await session.list_tools()
        row["list_seconds"] = round(time.perf_counter() - started, 3)
        before = json.dumps([t.model_dump(mode="json", exclude_none=True) for t in listing.tools], ensure_ascii=False)
        seen = before + (link["init"].instructions or "")
        started = time.perf_counter()
        first = await session.call_tool(*call)
        row["call_seconds"] = round(time.perf_counter() - started, 3)
        second = await session.call_tool(*call)
        seen += text_of(first)[:5000] + text_of(second)[:5000]
        await asyncio.sleep(0.2)
        after = json.dumps([t.model_dump(mode="json", exclude_none=True) for t in (await session.list_tools()).tools], ensure_ascii=False)
        row["tools"] = len(listing.tools)
        row["listing_chars"] = len(before)
        row["result_chars"] = len(text_of(first))
        row["hostile_content_delivered"] = bool(marker) and (marker in seen or marker in after)
        row["definition_changed_between_listings"] = before != after
        row["second_call_succeeded_after_change"] = before != after and not second.isError
        row["notifications"] = link.get("notifications", [])
        row["errors_or_warnings"] = 0
    return row


async def guarded_client(mode: str, call: tuple[str, dict], pins_path: str, verify_before_call: bool = True) -> dict:
    """The same visit through the guard: limits, scan, approval, pinned calls."""
    row: dict = {"stage": None, "reason": None}
    async with connect(HOSTILE, mode) as link:
        guard = GuardedSession(link["session"], f"hostile-{mode}", PinStore(pins_path), known_tools=OTHER_SERVERS_TOOLS,
                               verify_before_call=verify_before_call)
        link["guard"] = guard
        try:
            tools = await guard.list_tools()
        except Blocked as blocked:
            return {"stage": "listing", "reason": str(blocked)}
        findings = scan_listing(tools, link["init"].instructions, OTHER_SERVERS_TOOLS)
        if findings:
            return {"stage": "approval", "reason": "; ".join(sorted({f"{f.rule} ({f.where})" for f in findings}))[:300]}
        guard.pins.approve(guard.server, tools)  # a person looked at a clean scan and approved these definitions
        try:
            await guard.call_tool(*call)
            await asyncio.sleep(0.2)
            await guard.call_tool(*call)
        except Blocked as blocked:
            return {"stage": "call", "reason": str(blocked)}
    return row


async def hostile_servers(work: str) -> list[dict]:
    rows = []
    print(f"{'scenario':<20} {'plain client':<58} guarded client")
    for mode, attack, call, marker in SCENARIOS:
        plain = await plain_client(mode, call, marker)
        guarded = await guarded_client(mode, call, os.path.join(work, f"pins-{mode}.json"))
        if "observed" in plain:
            summary = plain["observed"]
        elif plain["definition_changed_between_listings"]:
            summary = f"changed definition accepted, second call ok, notifications {len(plain['notifications'])}"
        else:
            summary = f"delivered unchanged ({plain['listing_chars']:,} chars listed, {plain['result_chars']:,} returned)" if plain["hostile_content_delivered"] else "nothing hostile seen"
        verdict = f"stopped at {guarded['stage']}: {guarded['reason']}" if guarded["stage"] else "NOT STOPPED"
        print(f"{mode:<20} {summary:<58} {verdict[:150]}")
        rows.append({"mode": mode, "attack": attack, "plain": plain, "guarded": guarded})
    return rows


async def pin_modes(work: str) -> list[dict]:
    """The cheaper pin check trusts the server to announce changes. This is what that trust is worth."""
    rows = []
    print(f"\n{'server behaviour':<20} {'pin check':<44} outcome")
    for mode in ("rug-pull-silent", "rug-pull-notified"):
        for label, verify in (("before every call", True), ("on connect and on list_changed only", False)):
            result = await guarded_client(mode, ("add", {"a": 2, "b": 3}), os.path.join(work, f"pins-{mode}-{verify}.json"), verify)
            outcome = f"stopped at {result['stage']}" if result["stage"] else "NOT STOPPED: the changed tool was called"
            rows.append({"mode": mode, "pin_check": label, "stopped": bool(result["stage"])})
            print(f"{mode:<20} {label:<44} {outcome}")
    return rows


def corpus() -> dict:
    with open(HERE.parent / "corpus" / "descriptions.json", encoding="utf-8") as handle:
        entries = json.load(handle)["entries"]
    rows, tally = [], {"caught": 0, "missed": 0, "false_alarm": 0, "passed": 0}
    for entry in entries:
        findings = scan_listing([entry["tool"]], None, OTHER_SERVERS_TOOLS - {entry["tool"]["name"]})
        flagged, hostile = bool(findings), entry["label"] == "malicious"
        outcome = ("caught" if flagged else "missed") if hostile else ("false_alarm" if flagged else "passed")
        tally[outcome] += 1
        rows.append({"id": entry["id"], "label": entry["label"], "note": entry["note"], "outcome": outcome, "rules": sorted({f.rule for f in findings})})
    print(f"\nscanner on {len(entries)} hand-written tool definitions: {tally}")
    for row in rows:
        if row["outcome"] in ("missed", "false_alarm"):
            print(f"  {row['outcome']:<11} {row['id']}  {row['note']}  {row['rules']}")
    return {"tally": tally, "rows": rows}


class StandIn(http.server.BaseHTTPRequestHandler):
    """One handler, two roles: a partner API, and an internal metadata endpoint that must never be reachable."""
    metadata_url = ""

    def do_GET(self):  # noqa: N802
        if self.path == "/rates":
            body, status, headers = b'{"EUR": 1.0, "GBP": 0.86}', 200, {}
        elif self.path == "/moved":
            body, status, headers = b"", 302, {"Location": StandIn.metadata_url}
        elif self.path.startswith("/latest/meta-data"):
            body, status, headers = b'{"AccessKeyId": "FAKE-KEY-FOR-THE-LAB", "SecretAccessKey": "FAKE-NOT-A-SECRET"}', 200, {}
        else:
            body, status, headers = b"not found", 404, {}
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *arguments):  # keep the transcript clean
        pass


def serve() -> tuple[http.server.ThreadingHTTPServer, http.server.ThreadingHTTPServer]:
    partner = http.server.ThreadingHTTPServer(("127.0.0.1", 0), StandIn)
    metadata = http.server.ThreadingHTTPServer(("127.0.0.1", 0), StandIn)
    StandIn.metadata_url = f"http://127.0.0.1:{metadata.server_port}/latest/meta-data/iam/security-credentials/app-role"
    for instance in (partner, metadata):
        threading.Thread(target=instance.serve_forever, daemon=True).start()
    return partner, metadata


async def confused_deputy(work: str) -> list[dict]:
    root = Path(work) / "deputy"
    (root / "reports").mkdir(parents=True)
    (root / "secrets").mkdir()
    (root / "reports" / "q1.txt").write_text("Q1 report: revenue up 4%.", encoding="utf-8")
    (root / "secrets" / "db_password.txt").write_text("FAKE-PASSWORD-FOR-THE-LAB", encoding="utf-8")
    os.symlink(root / "secrets" / "db_password.txt", root / "reports" / "notes.txt")
    partner, metadata = serve()
    origin = f"http://localhost:{partner.server_port}"
    env = {**os.environ, "DEPUTY_ROOT": str(root), "DEPUTY_TENANT": "acme", "DEPUTY_ALLOWED_ORIGINS": origin}
    attacks = [
        ("Legitimate use", "read_report", {"name": "q1.txt"}, "Q1 report", False),
        ("Path traversal", "read_report", {"name": "../secrets/db_password.txt"}, "FAKE-PASSWORD", True),
        ("Symlink inside the folder", "read_report", {"name": "notes.txt"}, "FAKE-PASSWORD", True),
        ("Legitimate use", "fetch_rates", {"url": f"{origin}/rates"}, "GBP", False),
        ("Request to an internal address", "fetch_rates", {"url": StandIn.metadata_url}, "FAKE-KEY", True),
        ("Redirect from an approved host", "fetch_rates", {"url": f"{origin}/moved"}, "FAKE-KEY", True),
        ("Credentials in the URL", "fetch_rates", {"url": f"http://localhost:{partner.server_port}@127.0.0.1:{metadata.server_port}/latest/meta-data/x"}, "FAKE-KEY", True),
        ("Legitimate use", "get_invoice", {"invoice_id": "INV-1001", "tenant_id": "acme"}, "INV-1001", False),
        ("Another tenant's invoice", "get_invoice", {"invoice_id": "INV-2001", "tenant_id": "globex"}, "globex", True),
        ("Legitimate use", "find_invoices", {"status": "open"}, "INV-1001", False),
        ("SQL injection in a filter", "find_invoices", {"status": "x' OR '1'='1"}, "globex", True),
    ]
    rows = []
    print(f"\n{'attack':<32} {'tool':<14} {'naive version':<34} hardened version")
    async with connect(DEPUTY, env=env) as link:
        session = link["session"]
        for attack, tool, arguments, marker, hostile in attacks:
            outcomes = {}
            for variant, name in (("naive", f"{tool}_naive"), ("hardened", tool)):
                sent = arguments if variant == "naive" or "tenant_id" not in arguments else {"invoice_id": arguments["invoice_id"]}
                result = await session.call_tool(name, sent)
                body = text_of(result)
                if result.isError:
                    outcomes[variant] = "refused: " + " ".join(body.split())[:70]
                elif marker in body:
                    outcomes[variant] = ("LEAKED: " if hostile else "ok: ") + " ".join(body.split())[:40]
                else:
                    outcomes[variant] = "ok, nothing sensitive returned"
            rows.append({"attack": attack, "tool": tool, "hostile": hostile, **outcomes})
            print(f"{attack:<32} {tool:<14} {outcomes['naive'][:33]:<34} {outcomes['hardened'][:80]}")
    partner.shutdown(), metadata.shutdown()
    return rows


async def overhead(work: str, calls: int = 200) -> dict:
    """What the pin check costs: the same calls with and without a listing fetched before each one."""
    timings = {}
    for label, verify in (("verify before every call", True), ("verify on connect and on list_changed only", False)):
        async with connect(HOSTILE, "benign") as link:
            guard = GuardedSession(link["session"], "benign", PinStore(os.path.join(work, f"pins-overhead-{verify}.json")), verify_before_call=verify)
            link["guard"] = guard
            guard.pins.approve("benign", await guard.list_tools())
            started = time.perf_counter()
            for _ in range(calls):
                await guard.call_tool("add", {"a": 1, "b": 2})
            timings[label] = round((time.perf_counter() - started) / calls * 1000, 2)
    async with connect(HOSTILE, "benign") as link:
        started = time.perf_counter()
        for _ in range(calls):
            await link["session"].call_tool("add", {"a": 1, "b": 2})
        timings["no guard"] = round((time.perf_counter() - started) / calls * 1000, 2)
    print(f"\nmean milliseconds per call over {calls} calls on stdio: {timings}")
    return timings


async def main(out: str) -> int:
    os.makedirs(out, exist_ok=True)
    with tempfile.TemporaryDirectory() as work:
        report = {"hostile_servers": await hostile_servers(work), "pin_modes": await pin_modes(work), "corpus": corpus(),
                  "confused_deputy": await confused_deputy(work), "overhead_ms": await overhead(work)}
    with open(os.path.join(out, "red-team.json"), "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
    stopped = sum(1 for row in report["hostile_servers"] if row["guarded"]["stage"])
    leaks = [row for row in report["confused_deputy"] if row["hostile"]]
    print(f"\nhostile servers: {stopped} of {len(report['hostile_servers'])} stopped by the guard; the plain client raised no error in any of them")
    print(f"confused deputy: naive tools leaked in {sum(r['naive'].startswith('LEAKED') for r in leaks)} of {len(leaks)} attacks, "
          f"hardened tools in {sum(r['hardened'].startswith('LEAKED') for r in leaks)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1])))
