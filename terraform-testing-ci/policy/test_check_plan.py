"""python test_check_plan.py [compliant-plan.json noncompliant-plan.json]"""
import json
import pathlib
import sys

from check_plan import check

HERE = pathlib.Path(__file__).resolve().parent
passed = failed = 0


def expect(name: str, condition: bool, detail: object = "") -> None:
    global passed, failed
    passed += condition
    failed += not condition
    print(f"{'ok  ' if condition else 'FAIL'}  {name}{'' if condition else '  ' + str(detail)}")


fixture = json.loads((HERE / "fixtures" / "destroy-clinical-bucket.json").read_text(encoding="utf-8"))
findings = check(fixture)
expect("destroying a clinical bucket is refused", len(findings) == 1 and "module.discharge_summaries.aws_s3_bucket.this" in findings[0], findings)
expect("destroying an internal bucket is allowed", not any("build_cache" in f for f in findings), findings)
expect("a plan with no buckets has no findings", check({"resource_changes": [], "configuration": {"root_module": {}}}) == [])

if len(sys.argv) == 3:
    compliant = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    noncompliant = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
    expect("real plan of the module: no findings", check(compliant) == [], check(compliant))
    bad = check(noncompliant)
    expect("real plan of the hand-written bucket: four findings", len(bad) == 4, bad)
    expect("  force_destroy on clinical data", any("force_destroy" in f for f in bad), bad)
    expect("  encryption that is not SSE-KMS", any("AES256" in f for f in bad), bad)
    expect("  public access block partly off", any("block_public_policy, restrict_public_buckets" in f for f in bad), bad)
    expect("  versioning missing", any("versioning" in f for f in bad), bad)

print(f"\n{passed} of {passed + failed} checks passed")
sys.exit(1 if failed else 0)
