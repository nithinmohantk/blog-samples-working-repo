"""Asks a terminology server about every code from an external code system in the Bundles that were sent.

    python check_codes.py <output dir> [terminology server base, default https://tx.fhir.org/r4]

The validator run in this sample uses no terminology server, so it cannot say whether a SNOMED CT code exists or
whether the display beside it is one of that concept's terms. This does, with one $validate-code call per
distinct coding. Standard library only.
"""
import json
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

EXTERNAL = {"http://snomed.info/sct", "http://loinc.org"}
out = pathlib.Path(sys.argv[1])
server = (sys.argv[2] if len(sys.argv) > 2 else "https://tx.fhir.org/r4").rstrip("/")


def codings(node):
    if isinstance(node, dict):
        if node.get("system") in EXTERNAL and "code" in node:
            yield node["system"], node["code"], node.get("display", "")
        for value in node.values():
            yield from codings(value)
    elif isinstance(node, list):
        for value in node:
            yield from codings(value)


found = sorted({coding for file in sorted((out / "sent").glob("*.json")) for coding in codings(json.loads(file.read_text(encoding="utf-8")))})
if not found:
    raise SystemExit("No codings from an external code system were found in sent/.")
failed, rows = False, []
for system, code, display in found:
    query = urllib.parse.urlencode({"url": system, "code": code} | ({"display": display} if display else {}))
    request = urllib.request.Request(f"{server}/CodeSystem/$validate-code?{query}", headers={"Accept": "application/fhir+json"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            parameters = {p["name"]: next((v for k, v in p.items() if k.startswith("value")), None) for p in json.load(response).get("parameter", [])}
    except (urllib.error.URLError, TimeoutError) as error:
        parameters = {"result": False, "message": f"the terminology server did not answer: {error}"}
    ok = parameters.get("result") is True
    failed |= not ok
    rows.append({"system": system, "code": code, "display_sent": display, "result": parameters.get("result"), "display_on_server": parameters.get("display"),
                 "version": parameters.get("version"), "message": parameters.get("message")})
    print(f"{'ok  ' if ok else 'FAIL'}  {system} {code}  sent '{display}'  server '{parameters.get('display')}'{'' if ok else '  ' + str(parameters.get('message'))}")
(out / "codes.json").write_text(json.dumps({"server": server, "codings": rows}, indent=1) + "\n", encoding="utf-8")
print(f"\n{len(found)} distinct external coding(s) checked against {server}: {'FAILED' if failed else 'all valid'}")
sys.exit(1 if failed else 0)
