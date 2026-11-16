"""Run the lab: load synthetic data, start both MCP servers, and ask as eight different tokens.

Usage: python -m lab.run <output directory> [FHIR base URL]
Without a base URL the in-memory stand-in is started. Keys are generated for the run, kept in a
temporary directory and never written to the output.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from lab.data import bundle
from lab.judge import violations
from lab.probes import GENERIC, GENERIC_PROFILES, PROFILES, TYPED

ISSUER = "https://auth.lab.invalid"  # no authorization server runs here; the lab signs tokens itself


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for(port: int) -> None:
    for _ in range(200):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"nothing listening on {port}")


class Signer:
    def __init__(self, directory: str) -> None:
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.public_file = os.path.join(directory, "issuer-public.pem")
        with open(self.public_file, "wb") as handle:
            handle.write(self.key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))

    def mint(self, audience: str, scopes: str, patient: str | None, name: str, *, lifetime: int = 300, key=None) -> str:
        claims = {"iss": ISSUER, "aud": audience, "sub": f"user-{name}", "client_id": f"client-{name}", "scope": scopes, "iat": int(time.time()), "exp": int(time.time()) + lifetime}
        if patient:
            claims["patient"] = patient
        return jwt.encode(claims, key or self.key, algorithm="RS256")


async def ask(url: str, token: str, calls: list[tuple[str, dict]]) -> tuple[list[str], list[tuple[bool, object]]]:
    """List the tools, then make the calls. Returns the tool names and (is_error, payload) per call."""
    async with streamablehttp_client(url, headers={"Authorization": f"Bearer {token}"}) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            names = [tool.name for tool in (await session.list_tools()).tools]
            answers = []
            for tool, arguments in calls:
                result = await session.call_tool(tool, arguments)
                text = "\n".join(part.text for part in result.content if hasattr(part, "text"))
                payload: object = result.structuredContent
                if payload is None and not result.isError:
                    payload = json.loads(text)  # a tool that returns a plain dict answers with JSON text only
                answers.append((bool(result.isError), text if result.isError else payload))
            return names, answers


def holds_records(payload: object) -> bool:
    if isinstance(payload, dict) and "result" in payload and len(payload) == 1:
        payload = payload["result"]
    if isinstance(payload, list):
        return bool(payload)
    if isinstance(payload, dict):
        if payload.get("resourceType") == "Bundle":
            return bool(payload.get("entry"))
        if payload.get("resourceType") == "OperationOutcome":
            return False
        return payload.get("found", True) is not False
    return False


async def main(out: str, base: str | None) -> int:
    os.makedirs(out, exist_ok=True)
    work = tempfile.mkdtemp()
    signer = Signer(work)
    children: list[subprocess.Popen] = []
    failures = 0
    try:
        if base is None:
            port = free_port()
            children.append(subprocess.Popen([sys.executable, "-m", "lab.fhirstub", str(port)]))
            wait_for(port)
            base, backend = f"http://127.0.0.1:{port}/fhir", "in-memory stand-in"
        else:
            backend = httpx.get(base + "/metadata", timeout=60).json().get("software", {})
            backend = f"{backend.get('name')} {backend.get('version')}"
        httpx.post(base, json=bundle(), headers={"Content-Type": "application/fhir+json"}, timeout=120).raise_for_status()
        print(f"FHIR server: {backend}; {len(bundle()['entry'])} synthetic resources loaded")

        ports = {"server.app": free_port(), "lab.generic_server": free_port()}
        urls = {module: f"http://127.0.0.1:{port}/mcp" for module, port in ports.items()}
        audit = os.path.join(work, "audit.jsonl")
        for module, port in ports.items():
            env = {**os.environ, "FHIR_BASE": base, "MCP_ISSUER": ISSUER, "MCP_AUDIENCE": urls[module], "MCP_PUBLIC_KEY_FILE": signer.public_file, "MCP_AUDIT_LOG": audit, "MCP_PORT": str(port)}
            children.append(subprocess.Popen([sys.executable, "-m", "uvicorn", f"{module}:app", "--port", str(port), "--log-level", "warning"], env=env, stderr=open(os.path.join(out, f"{module}.stderr.txt"), "w")))
            wait_for(port)
        typed_url, generic_url = urls["server.app"], urls["lab.generic_server"]

        print("\n-- A. tools listed for each token")
        every = ["get_patient", "search_patients", "list_observations", "get_observation", "list_medications", "list_conditions", "record_observation"]
        print(f"{'token':<14} {'tools':>5}  " + " ".join(name[:11].ljust(11) for name in every))
        tokens = {name: signer.mint(typed_url, scopes, patient, name) for name, (scopes, patient) in PROFILES.items()}
        grouped: dict[str, list[tuple[str, dict, str]]] = {name: [] for name in PROFILES}
        for profile, tool, arguments, expected in TYPED:
            grouped[profile].append((tool, arguments, expected))
        records = []
        answers_by_profile = {}
        for name in PROFILES:
            names, answers = await ask(typed_url, tokens[name], [(tool, arguments) for tool, arguments, _ in grouped[name]])
            answers_by_profile[name] = (names, answers)
            print(f"{name:<14} {len(names):>5}  " + " ".join(("yes" if tool in names else "-").ljust(11) for tool in every))

        print("\n-- B. typed tools: each call against what should happen")
        print(f"{'token':<14} {'tool':<19} {'arguments':<44} {'expected':<8} {'got':<8} {'listed':<6} outside scope")
        for name in PROFILES:
            scopes, patient = PROFILES[name]
            names, answers = answers_by_profile[name]
            for (tool, arguments, expected), (is_error, payload) in zip(grouped[name], answers):
                got = "denied" if is_error and "DENIED" in str(payload) else "error" if is_error else "data" if holds_records(payload) else "empty"
                wrong = [] if is_error else violations(scopes.split(), patient, payload)
                shown = {k: v for k, v in arguments.items() if k in ("patient_id", "observation_id", "category", "family_name")}
                print(f"{name:<14} {tool:<19} {json.dumps(shown)[:44]:<44} {expected:<8} {got:<8} {'yes' if tool in names else 'no':<6} {', '.join(wrong) or 'none'}")
                records.append({"token": name, "tool": tool, "arguments": arguments, "expected": expected, "got": got, "listed": tool in names, "outside_scope": wrong})
                failures += got != expected or bool(wrong)
        agreed = sum(r["got"] == r["expected"] for r in records)
        hidden_denied = sum(1 for r in records if not r["listed"])
        print(f"\ntyped tools: {agreed} of {len(records)} calls ended as expected; {sum(bool(r['outside_scope']) for r in records)} returned a record outside the token's scopes")
        print(f"calls to a tool that was not listed for the token: {hidden_denied}, of which denied: {sum(1 for r in records if not r['listed'] and r['got'] == 'denied')}")

        print("\n-- C. tokens the server should not accept at all (HTTP status of the first request)")
        scopes, patient = PROFILES["patient-app"]
        bad = {
            "no token": None,
            "expired a minute ago": signer.mint(typed_url, scopes, patient, "expired", lifetime=-60),
            "signed by another key": signer.mint(typed_url, scopes, patient, "forged", key=signer.other),
            "minted for another server": signer.mint("https://other.lab.invalid/mcp", scopes, patient, "elsewhere"),
            "unsigned (alg none)": jwt.encode({"iss": ISSUER, "aud": typed_url, "sub": "x", "scope": scopes, "exp": int(time.time()) + 300}, None, algorithm="none"),
        }
        rejected = []
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        async with httpx.AsyncClient() as client:
            for label, token in bad.items():
                headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})}
                status = (await client.post(typed_url, json=body, headers=headers)).status_code
                print(f"{label:<28} HTTP {status}")
                rejected.append({"token": label, "status": status})
                failures += status != 401

        print("\n-- D. one generic tool that takes any FHIR path, two ways, on the same requests")
        print(f"{'token':<5} {'kind':<8} {'path':<58} {'naive':<22} guarded")
        generic_tokens = {name: signer.mint(generic_url, scopes, patient, name) for name, (scopes, patient) in GENERIC_PROFILES.items()}
        generic_records = []
        for profile, path, kind, purpose in GENERIC:
            scopes, patient = GENERIC_PROFILES[profile]
            _, answers = await ask(generic_url, generic_tokens[profile], [("fhir_request_naive", {"path": path}), ("fhir_request_guarded", {"path": path})])
            cells = {}
            for variant, (is_error, payload) in zip(("naive", "guarded"), answers):
                wrong = [] if is_error else violations(scopes.split(), patient, payload)
                cells[variant] = {"outcome": "refused" if is_error else f"LEAK {len(wrong)}" if wrong else "served" if holds_records(payload) else "nothing", "outside_scope": wrong}
            print(f"{profile:<5} {kind:<8} {path[:58]:<58} {cells['naive']['outcome']:<22} {cells['guarded']['outcome']}")
            generic_records.append({"token": profile, "path": path, "kind": kind, "purpose": purpose, **cells})
        summary = {}
        for variant in ("naive", "guarded"):
            hostile = [r for r in generic_records if r["kind"] == "hostile"]
            fair = [r for r in generic_records if r["kind"] == "fair"]
            summary[variant] = {"hostile": len(hostile), "leaked": sum(bool(r[variant]["outside_scope"]) for r in hostile), "records_leaked": sum(len(r[variant]["outside_scope"]) for r in generic_records), "fair": len(fair), "fair_served": sum(r[variant]["outcome"] == "served" for r in fair), "fair_leaked": sum(bool(r[variant]["outside_scope"]) for r in fair)}
            s = summary[variant]
            print(f"{variant}: {s['leaked']} of {s['hostile']} hostile requests returned a record outside scope ({s['records_leaked']} records over all requests); {s['fair_served']} of {s['fair']} fair requests served, {s['fair_leaked']} of them with a record outside scope")
        failures += summary["guarded"]["records_leaked"] > 0 or summary["guarded"]["fair_served"] != summary["guarded"]["fair"]

        print("\n-- E. audit log of the typed server")
        with open(audit, encoding="utf-8") as handle:
            lines = [json.loads(line) for line in handle]
        allowed = sum(line["outcome"] == "allowed" for line in lines)
        print(f"{len(lines)} lines for {len(records)} calls: {allowed} allowed, {len(lines) - allowed} denied")
        kinds: dict[str, int] = {}
        for line in lines:
            if line["outcome"] != "allowed":
                kinds[line["outcome"]] = kinds.get(line["outcome"], 0) + 1
        for kind, count in sorted(kinds.items(), key=lambda item: -item[1]):
            print(f"  {count:>2}  {kind}")
        leaked = [line for line in lines if any(word in json.dumps(line) for word in ("eyJ", "Alder", "Birch", "Hemoglobin"))]
        print(f"lines holding a token, a name or a result: {len(leaked)}")
        failures += bool(leaked)
        failures += len(lines) != len(records)

        with open(os.path.join(out, "results.json"), "w", encoding="utf-8") as handle:
            json.dump({"backend": backend, "tools_listed": {name: answers_by_profile[name][0] for name in PROFILES}, "typed": records, "rejected_tokens": rejected, "generic": generic_records, "generic_summary": summary, "audit": {"lines": len(lines), "allowed": allowed, "denied": kinds}}, handle, indent=1)
    finally:
        for child in children:
            child.terminate()
    print(f"\n{'OK' if not failures else f'FAILED: {failures} checks'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)))
