"""A validation gate for FHIR resources in a build pipeline.

Two commands:

  gate       Validate every resource under a directory. Exit 1 if any has an error. This is the build step.
  selfcheck  Validate the deliberately broken resources in testdata/ and check that each one is rejected, and
             that the valid ones pass. Exit 1 if the gate lets something through. This tests the gate itself.

Two engines produce the findings: the HL7 validator (a Java command-line tool, run from here) and a small
Firely SDK tool (run separately; its JSON output is read from --firely-results).

    python fhir_gate.py selfcheck --engine hl7 --jar validator_cli.jar --ig hl7.fhir.uv.ips#2.0.0 --tx n/a
    python fhir_gate.py gate --dir resources --engine hl7 --jar validator_cli.jar --ig hl7.fhir.uv.ips#2.0.0
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import time

FILE_EXTENSION = "http://hl7.org/fhir/StructureDefinition/operationoutcome-file"
BLOCKING = {"fatal", "error"}


def run_hl7_validator(jar: str, files: list[pathlib.Path], ig: list[str], tx: str | None, work: pathlib.Path,
                      java: str = "java", timeout: int = 1800) -> dict[str, list[dict]]:
    """Run the HL7 validator once over all files and return {file name: [issue, ...]}."""
    work.mkdir(parents=True, exist_ok=True)
    output = work / "hl7-output.json"
    command = [java, "-jar", jar, *[str(f) for f in files], "-version", "4.0.1", "-output", str(output)]
    for package in ig:
        command += ["-ig", package]
    if tx:
        command += ["-tx", tx]
    started = time.monotonic()
    completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    (work / "hl7-console.txt").write_text(
        f"$ {' '.join(command)}\nexit code {completed.returncode}, {time.monotonic() - started:.0f} s\n\n"
        f"{completed.stdout}\n{completed.stderr}", encoding="utf-8")
    if not output.exists():
        raise RuntimeError(f"The validator wrote no output (exit code {completed.returncode}). See {work / 'hl7-console.txt'}")
    return outcomes_by_file(json.loads(output.read_text(encoding="utf-8")), files)


def outcomes_by_file(document: dict, files: list[pathlib.Path]) -> dict[str, list[dict]]:
    """The validator writes one OperationOutcome for a single file and a Bundle of them for several."""
    outcomes = [document] if document.get("resourceType") == "OperationOutcome" else \
        [entry["resource"] for entry in document.get("entry", [])]
    by_name = {f.name: f for f in files}
    result: dict[str, list[dict]] = {}
    for index, outcome in enumerate(outcomes):
        named = next((e.get("valueString") for e in outcome.get("extension", []) if e.get("url") == FILE_EXTENSION), None)
        name = pathlib.Path(named).name if named else (files[index].name if index < len(files) else f"unknown-{index}")
        if name not in by_name:
            raise RuntimeError(f"The validator reported on '{named}', which is not one of the input files")
        result[name] = [{
            "severity": issue.get("severity", "error"),
            "code": issue.get("code", ""),
            "message": issue.get("details", {}).get("text") or issue.get("diagnostics", ""),
            "location": "; ".join(issue.get("expression", []) or issue.get("location", [])),
        } for issue in outcome.get("issue", [])]
    missing = set(by_name) - set(result)
    if missing:
        raise RuntimeError(f"The validator returned nothing for: {', '.join(sorted(missing))}")
    return result


def load_firely_results(path: str) -> dict[str, list[dict]]:
    return {pathlib.Path(name).name: issues for name, issues in json.loads(pathlib.Path(path).read_text(encoding="utf-8")).items()}


def errors(issues: list[dict]) -> list[dict]:
    return [i for i in issues if i["severity"] in BLOCKING]


def command_gate(args: argparse.Namespace) -> int:
    files = sorted(pathlib.Path(args.dir).rglob("*.json"))
    if not files:
        print(f"No resources under {args.dir}: refusing to pass an empty check")
        return 1
    findings = findings_for(args, files)
    failed = 0
    for file in files:
        blocking = errors(findings[file.name])
        failed += bool(blocking)
        print(f"{'FAIL' if blocking else 'ok  '}  {file}")
        for issue in blocking:
            print(f"        {issue['location'] or '-'}: {issue['message']}")
    print(f"\n{len(files) - failed} of {len(files)} resources conform")
    return 1 if failed else 0


def command_selfcheck(args: argparse.Namespace) -> int:
    root = pathlib.Path(args.testdata)
    cases = json.loads((root / "expectations.json").read_text(encoding="utf-8"))["cases"]
    files = [root / case["file"] for case in cases]
    findings = findings_for(args, files)
    terminology_on = args.engine == "hl7" and bool(args.tx) and args.tx.lower() != "n/a" or \
        (args.engine == "firely" and args.firely_terminology)
    rows, wrong = [], 0
    for case, file in zip(cases, files):
        blocking = errors(findings[file.name])
        verdict = "fail" if blocking else "pass"
        needs_terminology = case.get("needs") == "terminology-server"
        if needs_terminology and not terminology_on:
            status = "blind spot" if verdict == "pass" else "caught anyway"
        else:
            status = "as expected" if verdict == case["expect"] else "WRONG"
            wrong += status == "WRONG"
        rows.append({"file": case["file"], "expected": case["expect"], "verdict": verdict, "status": status,
                     "because": case.get("because", ""), "errors": [f"{i['location']}: {i['message']}"[:300] for i in blocking]})
        print(f"{status:<13} {verdict:<5} {case['file']}")
        for issue in blocking[:3]:
            print(f"              {issue['message'][:160]}")
    summary = {"engine": args.engine, "terminology": "on" if terminology_on else "off", "cases": len(rows), "wrong": wrong,
               "blindSpots": sum(r["status"] == "blind spot" for r in rows), "rows": rows}
    if args.report:
        pathlib.Path(args.report).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\n{len(rows) - wrong} of {len(rows)} cases as expected, {summary['blindSpots']} blind spot(s) without a terminology server")
    return 1 if wrong else 0


def findings_for(args: argparse.Namespace, files: list[pathlib.Path]) -> dict[str, list[dict]]:
    if args.engine == "firely":
        return load_firely_results(args.firely_results)
    return run_hl7_validator(args.jar, files, args.ig, args.tx, pathlib.Path(args.work))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("gate", "selfcheck"):
        sub = commands.add_parser(name)
        sub.add_argument("--engine", choices=["hl7", "firely"], default="hl7")
        sub.add_argument("--jar", default="validator_cli.jar")
        sub.add_argument("--ig", action="append", default=[], help="implementation guide package, for example hl7.fhir.uv.ips#2.0.0")
        sub.add_argument("--tx", help="terminology server URL, or n/a to validate without one")
        sub.add_argument("--work", default="out")
        sub.add_argument("--firely-results", help="JSON written by the FhirGate tool")
        sub.add_argument("--firely-terminology", action="store_true", help="the Firely run used a terminology server")
        sub.add_argument("--report", help="write the self-check result here as JSON")
    commands.choices["gate"].add_argument("--dir", required=True)
    commands.choices["selfcheck"].add_argument("--testdata", default="testdata")
    args = parser.parse_args()
    try:
        return command_gate(args) if args.command == "gate" else command_selfcheck(args)
    except (RuntimeError, subprocess.TimeoutExpired, OSError, json.JSONDecodeError) as error:
        print(f"The check could not run: {error}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
