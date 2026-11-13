"""Runs the HL7 FHIR validator over what the converter produced and decides from its findings.

    python validate_output.py validator_cli.jar <output dir> [--tx https://tx.fhir.org]

Two folders are checked. Every Bundle in sent/ (what was posted to the server) must have no errors. Every
resource in naive/ (v2 values copied across unchanged) must have at least one, which shows the validator is
looking. The validator's exit code is not used: the decision is read from the OperationOutcome it writes.
"""
import json
import pathlib
import subprocess
import sys
import time

FILE_EXTENSION = "http://hl7.org/fhir/StructureDefinition/operationoutcome-file"


def validate(jar: str, files: list[pathlib.Path], tx: str, work: pathlib.Path) -> dict[str, list[dict]]:
    output = work / "validator-output.json"
    command = ["java", "-jar", jar, *[str(f) for f in files], "-version", "4.0.1", "-tx", tx, "-output", str(output)]
    started = time.monotonic()
    done = subprocess.run(command, capture_output=True, text=True, timeout=1800)
    (work / "validator-console.txt").write_text(f"$ {' '.join(command)}\nexit code {done.returncode}, {time.monotonic() - started:.0f} s\n\n{done.stdout}\n{done.stderr}", encoding="utf-8")
    if not output.exists():
        raise SystemExit(f"The validator wrote no output (exit code {done.returncode}); see validator-console.txt")
    document = json.loads(output.read_text(encoding="utf-8"))
    outcomes = [document] if document.get("resourceType") == "OperationOutcome" else [e["resource"] for e in document.get("entry", [])]
    by_path = {str(f): f for f in files} | {f.name: f for f in files}
    result: dict[str, list[dict]] = {}
    for index, outcome in enumerate(outcomes):
        named = next((e.get("valueString") for e in outcome.get("extension", []) if e.get("url") == FILE_EXTENSION), None)
        source = by_path.get(named) or by_path.get(pathlib.Path(named or "").name) or files[index]
        result[f"{source.parent.name}/{source.name}"] = [{
            "severity": issue.get("severity", "error"),
            "message": issue.get("details", {}).get("text") or issue.get("diagnostics", ""),
            "location": "; ".join(issue.get("expression", []) or issue.get("location", [])),
        } for issue in outcome.get("issue", [])]
    return result


def main() -> int:
    jar, out = sys.argv[1], pathlib.Path(sys.argv[2])
    tx = sys.argv[sys.argv.index("--tx") + 1] if "--tx" in sys.argv else "https://tx.fhir.org"
    sent, naive = sorted((out / "sent").glob("*.json")), sorted((out / "naive").glob("*.json"))
    if not sent or not naive:
        raise SystemExit("Nothing to validate: run the self-test against a FHIR server first.")
    findings = validate(jar, sent + naive, tx, out)
    (out / "validation.json").write_text(json.dumps(findings, indent=1) + "\n", encoding="utf-8")

    failed = False
    warnings: dict[str, int] = {}
    for name, issues in findings.items():
        errors = [i for i in issues if i["severity"] in ("fatal", "error")]
        for issue in issues:
            if issue["severity"] == "warning":
                warnings[issue["message"]] = warnings.get(issue["message"], 0) + 1
        expected_bad = name.startswith("naive/")
        ok = bool(errors) if expected_bad else not errors
        failed |= not ok
        counts = f"{len(errors)} error(s), {sum(i['severity'] == 'warning' for i in issues)} warning(s)"
        print(f"{'ok  ' if ok else 'FAIL'}  {name:46} {counts}{'  (errors expected)' if expected_bad else ''}")
        for issue in errors:
            print(f"        error at {issue['location'] or '?'}: {issue['message'][:200]}")
    if warnings:
        print("\nwarnings, by message:")
        for message, count in sorted(warnings.items(), key=lambda item: -item[1]):
            print(f"  {count:3} x {message[:220]}")
    print(f"\n{len(sent)} Bundles as sent and {len(naive)} naive resources validated: {'gate FAILED' if failed else 'gate passed'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
