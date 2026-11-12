#!/usr/bin/env bash
# Everything the workflow runs. Usage: ./ci.sh <output directory>
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
here="$(cd "$(dirname "$0")" && pwd)"
cd "$here"
status=0
export TF_IN_AUTOMATION=1 TF_CLI_ARGS="-no-color" CHECKPOINT_DISABLE=1

terraform version | tee "$out/versions.txt"
tofu version | tee -a "$out/versions.txt"

echo "== terraform: init, validate, test"
( cd modules/secure-bucket && terraform init -input=false > "$out/terraform-init.txt" 2>&1 && terraform validate > "$out/terraform-validate.txt" 2>&1 \
  && terraform test 2>&1 | tee "$out/terraform-test.txt"; exit "${PIPESTATUS[0]}" ) || status=1
cp modules/secure-bucket/.terraform.lock.hcl "$out/terraform.lock.hcl"

echo "== opentofu: the same module and the same tests"
work="$(mktemp -d)"
cp -r modules/secure-bucket "$work/module" && rm -rf "$work/module/.terraform"
sed -i 's|registry.terraform.io|registry.opentofu.org|; /^  hashes = \[/,/^  \]/d' "$work/module/.terraform.lock.hcl"
( cd "$work/module" && tofu init -input=false > "$out/tofu-init.txt" 2>&1 && tofu validate > "$out/tofu-validate.txt" 2>&1 \
  && tofu test 2>&1 | tee "$out/tofu-test.txt"; exit "${PIPESTATUS[0]}" ) || { echo "tofu: FAILED" | tee -a "$out/tofu-test.txt"; status=1; }

echo "== mutations: each defect must make the tests fail"
: > "$out/mutations.txt"
while IFS='|' read -r name expression file; do
  case "$name" in ''|\#*) continue ;; esac
  copy="$(mktemp -d)"
  cp -r modules/secure-bucket/. "$copy/"
  sed -i -E -z "$expression" "$copy/$file" 2>/dev/null || sed -i "$expression" "$copy/$file"
  if cmp -s "$copy/$file" "modules/secure-bucket/$file"; then
    echo "$name: NOT APPLIED (the pattern did not match)" | tee -a "$out/mutations.txt"; status=1; continue
  fi
  result="$(cd "$copy" && terraform test 2>&1)"
  code=$?
  failed="$(echo "$result" | grep -E '^\s*run "[^"]+"\.\.\. fail' | sed -E 's/.*run "([^"]+)".*/\1/' | paste -sd, -)"
  if [ "$code" -ne 0 ]; then
    echo "$name: caught by ${failed:-the test run}" | tee -a "$out/mutations.txt"
  else
    echo "$name: SURVIVED (no test failed)" | tee -a "$out/mutations.txt"; status=1
  fi
  echo "$result" > "$out/mutation-$name.txt"
done < mutations.txt

echo "== plans for the policy gate"
for example in compliant noncompliant; do
  ( cd "examples/$example" && terraform init -input=false > "$out/plan-$example-init.txt" 2>&1 \
    && terraform plan -input=false -refresh=false -out=tfplan > "$out/plan-$example.txt" 2>&1 \
    && terraform show -json tfplan > "$out/plan-$example.json" ) || { echo "plan of $example failed"; tail -n 20 "$out/plan-$example.txt"; status=1; }
done

echo "== policy gate"
python policy/check_plan.py "$out/plan-compliant.json" | tee "$out/policy-compliant.txt"
[ "${PIPESTATUS[0]}" -eq 0 ] || { echo "the compliant plan was refused"; status=1; }
python policy/check_plan.py "$out/plan-noncompliant.json" | tee "$out/policy-noncompliant.txt"
[ "${PIPESTATUS[0]}" -eq 1 ] || { echo "the non-compliant plan was not refused"; status=1; }
python policy/check_plan.py policy/fixtures/destroy-clinical-bucket.json | tee "$out/policy-destroy.txt"
[ "${PIPESTATUS[0]}" -eq 1 ] || { echo "the destroy plan was not refused"; status=1; }
( cd policy && python test_check_plan.py "$out/plan-compliant.json" "$out/plan-noncompliant.json" ) | tee "$out/policy-tests.txt"
[ "${PIPESTATUS[0]}" -eq 0 ] || status=1

exit $status
