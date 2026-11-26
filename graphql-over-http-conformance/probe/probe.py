"""Sends the same 20 requests to each GraphQL server and compares the answers with the
GraphQL over HTTP specification, September 2026 edition (http-spec.graphql.org/September2026).

    python probe.py                      # all servers in SERVERS
    python probe.py --json results.json  # also write raw results
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from typing import Callable

import httpx

GQL = "application/graphql-response+json"
JSON = "application/json"

SERVERS = {
    "graphql-http 1.23.1": "http://127.0.0.1:4001/graphql",
    "GraphQL Yoga 6.1.1": "http://127.0.0.1:4002/graphql",
    "Apollo Server 5.5.2": "http://127.0.0.1:4003/graphql",
    "Mercurius 16.12.2": "http://127.0.0.1:4004/graphql",
    "Strawberry 0.341.3": "http://127.0.0.1:4005/graphql",
    "Ariadne 1.1.1": "http://127.0.0.1:4006/graphql",
}


@dataclass
class Answer:
    status: int
    content_type: str
    allow: str | None
    body: dict | str

    @property
    def media(self) -> str:
        return self.content_type.split(";")[0].strip().lower()

    @property
    def has_data(self) -> bool:
        return isinstance(self.body, dict) and self.body.get("data") is not None


# A check returns ("pass" | "should" | "must", note). "should" means the server is
# allowed to do what it did but the spec recommends something else; "must" is a
# violation of a MUST; "info" records behaviour the spec leaves open.
Check = Callable[[Answer], tuple[str, str]]


@dataclass
class Case:
    id: str
    title: str
    method: str
    headers: dict[str, str]
    body: str | None = None
    params: dict[str, str] | None = None
    check: Check = lambda a: ("info", "")


def post(query: str, **extra) -> str:
    return json.dumps({"query": query, **extra})


def expect_status(want: int, level: str = "should") -> Check:
    def check(a: Answer) -> tuple[str, str]:
        return ("pass", "") if a.status == want else (level, f"spec: {want}")
    return check


def all_of(*checks: Check) -> Check:
    def check(a: Answer) -> tuple[str, str]:
        worst, notes = "pass", []
        rank = {"pass": 0, "info": 0, "should": 1, "must": 2}
        for c in checks:
            level, note = c(a)
            if rank[level] > rank[worst]:
                worst = level
            if note:
                notes.append(note)
        return worst, "; ".join(notes)
    return check


def media_is(want: str, level: str = "must") -> Check:
    return lambda a: ("pass", "") if a.media == want else (level, f"spec: {want}")


def not_executed(a: Answer) -> tuple[str, str]:
    return ("pass", "") if not a.has_data else ("must", "mutation executed over GET")


def allow_header(a: Answer) -> tuple[str, str]:
    if a.status != 405:
        return "pass", ""
    return ("pass", "") if a.allow else ("must", "405 without Allow header (RFC 9110)")


def status_4xx(a: Answer) -> tuple[str, str]:
    return ("pass", "") if 400 <= a.status < 500 else ("should", "spec: a 4xx")


def accept_unsupported(a: Answer) -> tuple[str, str]:
    # MUST either answer 406 or ignore Accept; SHOULD answer 406.
    if a.status == 406:
        return "pass", ""
    if 200 <= a.status < 300:
        return "should", "ignored Accept (allowed), spec recommends 406"
    return "must", "neither 406 nor a normal response"


def partial(a: Answer) -> tuple[str, str]:
    if a.status == 294:
        return "pass", ""
    if a.status == 200:
        return "should", "200: allowed (2xx), status-code section recommends 294"
    return "must", "data present, so a 2xx is required"


ACC = {"accept": GQL, "content-type": JSON}
LEGACY = {"accept": JSON, "content-type": JSON}

CASES = [
    Case("A1", "POST, Accept graphql-response+json", "POST", ACC, post("{ hello }"),
         check=all_of(expect_status(200), media_is(GQL))),
    Case("A2", "POST, Accept application/json (legacy client)", "POST", LEGACY, post("{ hello }"),
         check=all_of(expect_status(200), media_is(JSON, "should"))),
    Case("A3", "POST, Accept both, graphql-response+json preferred", "POST",
         {"accept": f"{GQL}, {JSON};q=0.9", "content-type": JSON}, post("{ hello }"),
         check=media_is(GQL)),
    Case("A4", "POST, no Accept header", "POST", {"content-type": JSON}, post("{ hello }")),
    Case("A5", "POST, Accept text/html only", "POST", {"accept": "text/html", "content-type": JSON},
         post("{ hello }"), check=accept_unsupported),
    Case("B1", "POST, Content-Type text/plain", "POST", {"accept": GQL, "content-type": "text/plain"},
         post("{ hello }"), check=expect_status(415)),
    Case("B2", "POST, no Content-Type", "POST", {"accept": GQL}, post("{ hello }"), check=status_4xx),
    Case("B3", "POST, body is not JSON", "POST", ACC, "NONSENSE", check=expect_status(400)),
    Case("B4", "POST, misspelt parameter (qeury)", "POST", ACC, json.dumps({"qeury": "{ hello }"}),
         check=expect_status(422)),
    Case("B5", "POST, variables is an array", "POST", ACC,
         post("query Q($id: ID!) { user(id: $id) { name } }", variables=[7]), check=expect_status(422)),
    Case("B6", "POST, unknown top-level property", "POST", ACC, post("{ hello }", trace=True),
         check=expect_status(200, "must")),
    Case("C1", "Document does not parse", "POST", ACC, post("{"), check=expect_status(400)),
    Case("C2", "Validation error (unknown field)", "POST", ACC, post("{ nope }"), check=expect_status(422)),
    Case("C3", "Two operations, no operationName", "POST", ACC, post("query A { hello } query B { hello }"),
         check=expect_status(422)),
    Case("C4", "Required variable missing", "POST", ACC, post("query Q($id: ID!) { user(id: $id) { name } }"),
         check=expect_status(422)),
    Case("C5", "Partial result (data and errors)", "POST", ACC, post("{ hello boom }"), check=partial),
    Case("C6", "Validation error, legacy Accept application/json", "POST", LEGACY, post("{ nope }"),
         check=expect_status(422)),
    Case("D1", "GET query", "GET", {"accept": GQL}, params={"query": "{ hello }"},
         check=expect_status(200, "info")),
    Case("D2", "GET mutation", "GET", {"accept": GQL},
         params={"query": 'mutation { setGreeting(text: "hi") }'},
         check=all_of(expect_status(405), not_executed, allow_header, status_4xx)),
    Case("D3", "PUT", "PUT", ACC, post("{ hello }"), check=expect_status(405)),
    # Apollo Server's CSRF prevention refuses GET requests that a browser could send without a
    # preflight. The spec's security notes mention this pattern; these two repeat D1 and D2 with a
    # header Apollo accepts. The header means nothing to the other servers.
    Case("D4", "GET query + apollo-require-preflight", "GET", {"accept": GQL, "apollo-require-preflight": "true"},
         params={"query": "{ hello }"}, check=expect_status(200, "info")),
    Case("D5", "GET mutation + apollo-require-preflight", "GET", {"accept": GQL, "apollo-require-preflight": "true"},
         params={"query": 'mutation { setGreeting(text: "hi") }'},
         check=all_of(expect_status(405), not_executed, allow_header, status_4xx)),
]


def send(client: httpx.Client, url: str, case: Case) -> Answer:
    r = client.request(case.method, url, headers=case.headers, content=case.body, params=case.params)
    try:
        body: dict | str = r.json()
    except ValueError:
        body = r.text[:120]
    return Answer(r.status_code, r.headers.get("content-type", "-"), r.headers.get("allow"), body)


def body_matches_status(a: Answer) -> tuple[str, str]:
    """Rules that apply to every application/graphql-response+json answer."""
    if a.media != GQL or not isinstance(a.body, dict):
        return "pass", ""
    if "data" not in a.body and a.status < 400:
        return "must", f"{a.status} for a result without data (spec: 4xx or 5xx)"
    if a.body.get("data") is not None and not 200 <= a.status < 300:
        return "must", f"{a.status} for a result with data (spec: 2xx)"
    return "pass", ""


def graphiql_page(case: Case, a: Answer) -> bool:
    return case.method == "GET" and a.media == "text/html"


def run(servers: dict[str, str]) -> dict[str, list[dict]]:
    results: dict[str, list[dict]] = {}
    with httpx.Client(timeout=10, trust_env=False) as client:
        for name, url in servers.items():
            rows = []
            for case in CASES:
                a = send(client, url, case)
                if graphiql_page(case, a):
                    verdict, note = "info", "GET returned the GraphiQL page, not a GraphQL response"
                else:
                    verdict, note = case.check(a)
                    extra, extra_note = body_matches_status(a)
                    if extra == "must":
                        verdict, note = "must", "; ".join(x for x in (note, extra_note) if x)
                rows.append({"case": case.id, "title": case.title, "status": a.status,
                             "content_type": a.media, "allow": a.allow, "verdict": verdict,
                             "note": note, "body": a.body})
            results[name] = rows
    return results


def table(results: dict[str, list[dict]]) -> str:
    mark = {"pass": "ok", "should": "~", "must": "X", "info": "."}
    names = list(results)
    lines = ["| Case | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for i, case in enumerate(CASES):
        cells = []
        for n in names:
            r = results[n][i]
            ct = {"application/graphql-response+json": "gql", "application/json": "json"}.get(r["content_type"], r["content_type"])
            cells.append(f"{r['status']} {ct} {mark[r['verdict']]}")
        lines.append(f"| {case.id} {case.title} | " + " | ".join(cells) + " |")
    lines.append("| **MUST violations / SHOULD differences** | " + " | ".join(
        f"{sum(r['verdict'] == 'must' for r in results[n])} / {sum(r['verdict'] == 'should' for r in results[n])}"
        for n in names) + " |")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    args = ap.parse_args()
    results = run(SERVERS)
    print(table(results))
    print("\nok = as the spec says, ~ = allowed but not what the spec recommends (SHOULD),"
          " X = breaks a MUST, . = left open by the spec. gql = application/graphql-response+json")
    for n, rows in results.items():
        notes = [f"  {r['case']}: {r['note']}" for r in rows if r["verdict"] in ("must", "should") and r["note"]]
        if notes:
            print(f"\n{n}\n" + "\n".join(notes))
    if args.json:
        with open(args.json, "w") as f:
            json.dump(results, f, indent=2, default=str)


if __name__ == "__main__":
    main()
