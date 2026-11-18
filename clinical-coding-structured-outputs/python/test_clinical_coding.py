"""Runs fixtures/scenario.json through the pipeline. Usage: python test_clinical_coding.py [bundle-output.json]"""
import json
import pathlib
import sys

import clinical_coding as cc

ROOT = pathlib.Path(__file__).resolve().parent.parent
subset = cc.load_subset(str(ROOT / "terminology" / "coding-subset.json"))
scenario = json.loads((ROOT / "fixtures" / "scenario.json").read_text(encoding="utf-8"))
passed = failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    passed += condition
    failed += not condition
    print(f"{'ok  ' if condition else 'FAIL'}  {name}{'' if condition else '  ' + detail}")


schema = cc.build_schema(subset)
check("schema meets the strict structured output limits", cc.lint_schema(schema) == [], str(cc.lint_schema(schema)))
bad = json.loads(json.dumps(schema))
bad["properties"]["conditions"]["items"]["properties"]["evidence"]["minLength"] = 1
bad["properties"]["observations"]["items"]["required"].remove("unit")
check("schema lint finds an unsupported keyword and an optional property", len(cc.lint_schema(bad)) == 2, str(cc.lint_schema(bad)))
check("schema enums are the subset", schema["properties"]["conditions"]["items"]["properties"]["code"]["enum"] == list(subset["conditions"]) + ["uncoded"])
check("prompt lists every code", all(code in cc.system_prompt(subset) for kind in subset.values() for code in kind))

proposals = {}
for name, response in scenario["responses"].items():
    note = scenario["notes"][response["note"]]
    proposals[name] = cc.guard(cc.parse_response(json.dumps(response["content"]), subset), note["text"], subset)
    actual = {p["id"]: p["status"] for p in proposals[name]}
    check(f"guard, {name} response: statuses", actual == response["expected"], str(actual))

by_id = {p["id"]: p for p in proposals["careless"]}
check("fabricated evidence is blocked", by_id["c1"]["reasons"] == ["the evidence is not text from the note"])
check("a value that differs from the evidence is blocked", by_id["o1"]["reasons"] == ["the value does not appear in the evidence"])
check("an unconverted unit is blocked", by_id["o2"]["reasons"] == ["only Cel is accepted for this code: enter by hand"])
check("an uncoded condition reaches review with a flag", by_id["c4"]["code"] is None and len(by_id["c4"]["flags"]) == 1)
check("a wrong assertion passes the guard (the reviewer has to catch it)", by_id["c5"]["status"] == "for_review")
check("an implausible value is flagged, not blocked", len(proposals["implausible"][0]["flags"]) == 1 and proposals["implausible"][1]["flags"] == [])

for case in scenario["malformed"]:
    try:
        cc.parse_response(case["raw"], subset)
        check(f"malformed response refused: {case['name']}", False, "accepted")
    except cc.ShapeError:
        check(f"malformed response refused: {case['name']}", True)

review = scenario["review"]
careful = proposals[review["response"]]
for case in review["refused"]:
    try:
        cc.apply_review(careful, [case["decision"]], subset)
        check(f"review refused: {case['name']}", False, "accepted")
    except cc.ReviewError:
        check(f"review refused: {case['name']}", True)
try:
    cc.apply_review(careful, [review["decisions"][0], review["decisions"][0]], subset)
    check("review refused: two decisions for one proposal", False)
except cc.ReviewError:
    check("review refused: two decisions for one proposal", True)
try:
    cc.apply_review(proposals["careless"], [{"proposal": "c4", "action": "accept"}], subset)
    check("review refused: accepting an uncoded condition", False)
except cc.ReviewError:
    check("review refused: accepting an uncoded condition", True)
recoded = cc.apply_review(proposals["careless"], [{"proposal": "c4", "action": "recode", "code": "49436004"}, {"proposal": "c5", "action": "reject"}], subset)
check("recode gives the subset's display; reject gives nothing", len(recoded) == 1 and recoded[0]["display"] == "Atrial fibrillation (disorder)")

accepted = cc.apply_review(careful, review["decisions"], subset)
note = scenario["notes"][scenario["responses"][review["response"]]["note"]]
bundle = cc.to_bundle(accepted, note, review, subset)
types = [e["resource"]["resourceType"] for e in bundle["entry"]]
check("bundle: 4 conditions, 5 observations, 1 provenance", (types.count("Condition"), types.count("Observation"), types.count("Provenance")) == (4, 5, 1), str(types))
statuses = [e["resource"]["verificationStatus"]["coding"][0]["code"] for e in bundle["entry"] if e["resource"]["resourceType"] == "Condition"]
check("bundle: three confirmed, one provisional", statuses == ["confirmed", "confirmed", "confirmed", "provisional"])
codes = {e["resource"]["code"]["coding"][0]["code"] for e in bundle["entry"] if "code" in e["resource"]}
check("bundle: nothing negated, familial or undecided was written", not codes & {"29857009", "386661006", "22298006"})
provenance = bundle["entry"][-1]["resource"]
check("bundle: provenance targets every resource and names reviewer and device", len(provenance["target"]) == 9 and len(provenance["agent"]) == 2)
check("no decisions, no resources", cc.to_bundle(cc.apply_review(careful, [], subset), note, review, subset)["entry"] == [])
check("same input, same bundle", bundle == cc.to_bundle(cc.apply_review(careful, review["decisions"], subset), note, review, subset))

if len(sys.argv) > 1:
    pathlib.Path(sys.argv[1]).write_text(json.dumps(bundle, indent=2), encoding="utf-8")
print(f"\n{passed} of {passed + failed} checks passed")
sys.exit(1 if failed else 0)
