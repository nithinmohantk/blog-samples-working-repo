#!/usr/bin/env bash
# Everything the workflow runs. Usage: ./ci.sh <output directory>
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
status=0
export TF_IN_AUTOMATION=1 TF_CLI_ARGS="-no-color" CHECKPOINT_DISABLE=1

echo "== the contract copies are current"
python contract/render.py --check | tee "$out/contract-check.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1

: > "$out/init-cost.txt"
for module in network-baseline-aws network-baseline-azure facade; do
  echo "== terraform: $module"
  ( cd "modules/$module"
    start=$(date +%s.%N)
    terraform init -input=false > "$out/$module-init.txt" 2>&1; code=$?
    end=$(date +%s.%N)
    size=$(du -sm .terraform/providers 2>/dev/null | cut -f1)
    printf '%s: init %.0f s, providers on disk %s MB\n' "$module" "$(echo "$end - $start" | bc)" "${size:-?}" >> "$out/init-cost.txt"
    [ $code -eq 0 ] && terraform validate > "$out/$module-validate.txt" 2>&1 && terraform test 2>&1 | tee "$out/$module-terraform-test.txt"; exit "${PIPESTATUS[0]}" ) || { status=1; tail -n 25 "$out/$module-validate.txt" "$out/$module-init.txt" 2>/dev/null | tail -n 40; }

  echo "== opentofu: $module"
  work="$(mktemp -d)"
  cp -r modules "$work/modules" && find "$work" -name .terraform -type d -prune -exec rm -rf {} +
  sed -i 's|registry.terraform.io|registry.opentofu.org|; /^  hashes = \[/,/^  \]/d' "$work/modules/$module/.terraform.lock.hcl"
  ( cd "$work/modules/$module" && tofu init -input=false > "$out/$module-tofu-init.txt" 2>&1 \
    && tofu test 2>&1 | tee "$out/$module-tofu-test.txt"; exit "${PIPESTATUS[0]}" ) || { echo "tofu: FAILED" | tee -a "$out/$module-tofu-test.txt"; status=1; }
done
cat "$out/init-cost.txt"

echo "== drift: an edit to one copy of the contract must be noticed"
copy="$(mktemp -d)" && cp -r . "$copy/" 2>/dev/null
sed -i 's/log_retention_days >= 90/log_retention_days >= 30/' "$copy/modules/network-baseline-azure/contract_variables.tf"
( cd "$copy" && python contract/render.py --check ) > "$out/drift-check.txt" 2>&1 && { echo "drift was not noticed"; status=1; }
cat "$out/drift-check.txt"
( cd "$copy/modules/network-baseline-azure" && terraform init -input=false > /dev/null 2>&1; terraform test 2>&1 | grep -E 'run "|passed|failed' ) > "$out/drift-test.txt"
grep -E "fail" "$out/drift-test.txt" || { echo "the contract test did not catch the weakened rule"; status=1; }

exit $status
