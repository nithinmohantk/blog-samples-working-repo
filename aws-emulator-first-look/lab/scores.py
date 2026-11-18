"""Summarises the fidelity scores AWS publishes with each emulator release.

    python scores.py out/

Downloads scores.json.gz from the latest GitHub release of aws/aws-emulator and counts passes by service.
A unit is one fidelity test. A test that touches several services is counted under each of them.
"""
import collections
import gzip
import json
import os
import sys
import urllib.request

out = sys.argv[1]
headers = {"Accept": "application/vnd.github+json"}
if os.environ.get("GITHUB_TOKEN"):
    headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]


def get(url: str, with_headers: bool) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers if with_headers else {}), timeout=120) as response:
        return response.read()


release = json.loads(get("https://api.github.com/repos/aws/aws-emulator/releases/latest", True))
print("release", release["tag_name"], "published", release["published_at"])
with open(os.path.join(out, "release-notes.md"), "w", encoding="utf-8") as handle:
    handle.write(release.get("body") or "")
fixes = sum(1 for line in (release.get("body") or "").splitlines() if line.strip().startswith("- fix"))
print("fixes listed in the release notes:", fixes)
asset = next(a for a in release["assets"] if a["name"] == "scores.json.gz")
scores = json.loads(gzip.decompress(get(asset["browser_download_url"], False)))
units = scores["units"]
overall = collections.Counter(unit["outcome"] for unit in units)
kinds = collections.Counter((unit["kind"], unit["outcome"]) for unit in units)
by_service: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
for unit in units:
    for service in unit["services"]:
        by_service[service.split("#")[0].removeprefix("com.amazonaws.")][unit["outcome"]] += 1
mismatches = collections.Counter(unit["detail"].get("mismatch", "?") for unit in units if unit["outcome"] == "fail")

summary = {
    "release": release["tag_name"], "published": release["published_at"], "commit": scores["commit"], "scoredAt": scores["scoredAt"],
    "fixes_in_release_notes": fixes, "units": len(units), "overall": dict(overall),
    "by_kind": {f"{kind} {outcome}": count for (kind, outcome), count in sorted(kinds.items())},
    "failure_mismatch_kinds": dict(mismatches.most_common(8)), "services_with_tests": len(by_service),
    "services": {name: {"pass": c["pass"], "fail": c["fail"], "skipped": c["skipped"]} for name, c in sorted(by_service.items())},
}
with open(os.path.join(out, "scores-summary.json"), "w", encoding="utf-8") as handle:
    json.dump(summary, handle, indent=1)
    handle.write("\n")
scored = overall["pass"] + overall["fail"]
print(f"{len(units)} fidelity tests: {overall['pass']} pass, {overall['fail']} fail, {overall['skipped']} skipped ({100 * overall['pass'] / scored:.1f}% of those scored)")
print(f"{len(by_service)} services have at least one test")
print("why tests fail:", ", ".join(f"{kind} {count}" for kind, count in mismatches.most_common(6)))
print(f"{'service':28}{'pass':>7}{'total':>7}{'%':>7}")
for name in ("s3", "dynamodb", "sqs", "sns", "lambda", "iam", "sts", "secretsmanager", "sfn", "states", "eventbridge", "kms", "ec2", "cloudformation", "kinesis", "ssm", "apigateway", "ecs", "rds", "bedrockruntime"):
    if name in by_service:
        c = by_service[name]
        total = c["pass"] + c["fail"]
        print(f"{name:28}{c['pass']:>7}{total:>7}{100 * c['pass'] / max(total, 1):>6.0f}%")
