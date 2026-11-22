"""A real browser against the published web host and the agent service.
Usage: python e2e/run.py <web host url> <agent url> <output dir>

Chromium loads the WebAssembly app, signs in through the lab sign-in page, and uses the chat.
What the agent service did is read over its lab endpoints after each step.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

from playwright.sync_api import Page, expect, sync_playwright

WEB, AGENT, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
results: list[dict] = []
BOX = "textarea.sc-ai-input__textarea"


def lab(path: str):
    with urllib.request.urlopen(f"{AGENT}{path}", timeout=10) as response:
        return json.load(response)


def ask(page: Page, text: str) -> None:
    box = page.locator(BOX)
    expect(box).to_be_enabled(timeout=20000)
    box.fill(text)
    page.locator("button.sc-ai-input__send").click()


def step(name: str, check) -> None:
    started = time.monotonic()
    try:
        detail = check()
        results.append({"step": name, "ok": True, "seconds": round(time.monotonic() - started, 2), "detail": detail})
    except Exception as error:  # a failed step is recorded and the run goes on, so one report shows everything
        results.append({"step": name, "ok": False, "seconds": round(time.monotonic() - started, 2), "detail": str(error).splitlines()[0][:400]})
    print(("ok   " if results[-1]["ok"] else "FAIL ") + f"{name}: {results[-1]['detail']}")


def main() -> int:
    urllib.request.urlopen(urllib.request.Request(f"{AGENT}/reset", method="POST"), timeout=10).close()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1376, "height": 768})
        page = context.new_page()
        hosts: dict[str, int] = {}
        with_authorization: list[str] = []
        downloads: list[tuple[str, int, str, bool]] = []
        console: list[str] = []

        def on_request(request):
            host = request.url.split("/")[2]
            hosts[host] = hosts.get(host, 0) + 1
            if "authorization" in {name.lower() for name in request.headers}:
                with_authorization.append(request.url)

        # Sizes come from the browser's own network log: bytes that crossed the wire, and what came from its cache.
        network = context.new_cdp_session(page)
        network.send("Network.enable")
        pending: dict[str, dict] = {}

        def on_response(event):
            headers = {name.lower(): value for name, value in event["response"]["headers"].items()}
            pending[event["requestId"]] = {"url": event["response"]["url"], "encoding": headers.get("content-encoding", "none"), "cached": event["response"].get("fromDiskCache", False)}

        def on_finished(event):
            if (entry := pending.pop(event["requestId"], None)) is not None:
                downloads.append((entry["url"], int(event["encodedDataLength"]), entry["encoding"], entry["cached"]))

        network.on("Network.responseReceived", on_response)
        network.on("Network.loadingFinished", on_finished)
        page.on("request", on_request)
        page.on("console", lambda message: console.append(f"{message.type}: {message.text}"[:300]) if message.type in ("error", "warning") else None)

        def sign_in_required():
            page.goto(WEB)
            expect(page.get_by_role("button", name="Sign in as Sam")).to_be_visible(timeout=15000)
            page.screenshot(path=f"{OUT}/shot-1-sign-in.png")
            return f"an address without a session ends at {page.url.replace(WEB, '')}"

        def first_load():
            downloads.clear()
            started = time.monotonic()
            page.get_by_role("button", name="Sign in as Sam").click()
            expect(page.locator(BOX)).to_be_enabled(timeout=60000)
            seconds = time.monotonic() - started
            expect(page.locator(".desk__user")).to_have_text("Sam (order desk)", timeout=15000)
            page.wait_for_timeout(500)
            framework = [entry for entry in downloads if "/_framework/" in entry[0]]
            encodings = sorted({entry[2] for entry in framework})
            return (f"chat usable {seconds:.1f} s after the click, empty cache; {len(downloads)} responses, {sum(e[1] for e in downloads) / 1024:.0f} KiB over the wire, "
                    f"of which {len(framework)} files and {sum(e[1] for e in framework) / 1024:.0f} KiB under /_framework/ (content-encoding: {', '.join(encodings)})")

        def second_load():
            downloads.clear()
            started = time.monotonic()
            page.reload()
            expect(page.locator(BOX)).to_be_enabled(timeout=60000)
            seconds = time.monotonic() - started
            page.wait_for_timeout(500)
            cached = sum(1 for entry in downloads if entry[3])
            return f"reload: chat usable after {seconds:.1f} s; {len(downloads)} responses, {cached} from the browser cache, {sum(e[1] for e in downloads) / 1024:.0f} KiB over the wire"

        def order_card():
            ask(page, "Where is order O-1001?")
            card = page.locator(".order-card[data-order='O-1001']")
            expect(card).to_contain_text("Synthetic kettle", timeout=20000)
            expect(page.get_by_text("Here is the order.")).to_be_visible(timeout=15000)
            return card.inner_text().replace("\n", " | ")

        def streams_and_stops():
            ask(page, "Explain the refund policy")
            button = page.locator("button.desk-stop")
            expect(button).to_be_visible(timeout=15000)
            seen = []
            for _ in range(5):
                page.wait_for_timeout(600)
                text = page.locator("body").inner_text()
                seen.append(len(text[text.rfind("Explain the refund policy"):].split()) - 4)
            button.click()
            expect(button).to_be_hidden(timeout=15000)
            expect(page.locator(BOX)).to_be_enabled(timeout=15000)
            page.wait_for_timeout(1500)
            last = lab("/wire")[-1]
            assert seen[-1] > seen[0], seen
            assert last["completed"] is False and last["last"] != "RUN_FINISHED", last
            return f"words of the answer on the page at 0.6 s intervals: {seen}; after Stop the agent service stream ended early after {last['events']} events, no RUN_FINISHED"

        def approve_within_limit():
            ask(page, "Refund order O-1003")
            approve = page.locator(".sc-ai-approval").last.get_by_role("button", name="Approve")
            expect(approve).to_be_visible(timeout=15000)
            assert lab("/ledger")["attempts"] == 0
            approve.click()
            expect(page.get_by_text("The refund is recorded.")).to_be_visible(timeout=15000)
            refunds = lab("/ledger")["refunds"]
            assert [(r["orderId"], r["approvedBy"]) for r in refunds] == [("O-1003", "sam")], refunds
            return f"refunds: {[(r['orderId'], r['amount'], r['approvedBy']) for r in refunds]}"

        def approve_above_limit():
            ask(page, "Refund order O-1001")
            page.locator(".sc-ai-approval").last.get_by_role("button", name="Approve").click()
            expect(page.get_by_text("a supervisor has to approve it")).to_be_visible(timeout=15000)
            page.wait_for_timeout(300)
            page.screenshot(path=f"{OUT}/shot-2-above-limit.png")
            state = lab("/ledger")
            assert len(state["refunds"]) == 1, state
            return f"Sam clicked Approve on 42.00; refunds still {len(state['refunds'])}; the agent said it needs a supervisor"

        def nothing_to_steal():
            cookies = context.cookies()
            session = [c for c in cookies if c["name"] == "desk.session"]
            visible = page.evaluate("() => ({cookie: document.cookie, local: Object.keys(localStorage), session: Object.keys(sessionStorage)})")
            agent_host = AGENT.split("/")[2]
            assert session and session[0]["httpOnly"] and session[0]["sameSite"] == "Strict", session
            assert visible["cookie"] == "" and not any("token" in key.lower() for key in visible["local"] + visible["session"]), visible
            assert not with_authorization, with_authorization[:3]
            assert agent_host not in hosts, hosts
            return (f"document.cookie is empty; session cookie httpOnly={session[0]['httpOnly']} sameSite={session[0]['sameSite']}; "
                    f"requests carrying an Authorization header: {len(with_authorization)}; hosts the browser talked to: {sorted(hosts)}")

        def header_is_required():
            status = page.evaluate("""async () => (await fetch('/agent', {method: 'POST', headers: {'content-type': 'application/json'}, body: '{}'})).status""")
            assert status == 400, status
            return f"a POST from the page without X-Desk-Client: HTTP {status}"

        def session_ends():
            context.clear_cookies()
            box = page.locator(BOX)
            box.fill("Where is order O-1002?")
            page.locator("button.sc-ai-input__send").click()
            expect(page.get_by_role("button", name="Sign in as Alex")).to_be_visible(timeout=15000)
            return f"with the cookie gone, the next question ended at {page.url.replace(WEB, '')}; the conversation on the page is lost"

        def supervisor():
            page.get_by_role("button", name="Sign in as Alex").click()
            expect(page.locator(".desk__user")).to_have_text("Alex (supervisor)", timeout=60000)
            ask(page, "Refund order O-1001")
            page.locator(".sc-ai-approval").last.get_by_role("button", name="Approve").click()
            expect(page.get_by_text("The refund is recorded.")).to_be_visible(timeout=15000)
            page.wait_for_timeout(300)
            page.screenshot(path=f"{OUT}/shot-3-supervisor.png")
            refunds = lab("/ledger")["refunds"]
            assert [(r["orderId"], r["approvedBy"]) for r in refunds] == [("O-1003", "sam"), ("O-1001", "alex")], refunds
            return f"refunds: {[(r['orderId'], r['amount'], r['approvedBy']) for r in refunds]}"

        step("no session: the app is not served", sign_in_required)
        step("first load of the WebAssembly app", first_load)
        step("second load", second_load)
        step("order card from a backend tool", order_card)
        step("the answer streams in the browser, and Stop reaches the agent service", streams_and_stops)
        step("Sam approves a refund inside the limit", approve_within_limit)
        step("Sam approves a refund above the limit", approve_above_limit)
        step("nothing in the browser to steal", nothing_to_steal)
        step("the cross-site check", header_is_required)
        step("the session ends in the middle of a conversation", session_ends)
        step("Alex approves the refund Sam could not", supervisor)
        browser.close()

    with open(f"{OUT}/e2e.json", "w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=1)
    with open(f"{OUT}/browser-console.txt", "w", encoding="utf-8") as handle:
        handle.write("\n".join(console) + "\n")
    passed = sum(r["ok"] for r in results)
    print(f"{passed} of {len(results)} browser steps passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
