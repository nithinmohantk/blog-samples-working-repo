#!/usr/bin/env bash
# Everything the workflow runs. Usage: ./ci.sh <output directory>
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
status=0
export TF_IN_AUTOMATION=1 TF_CLI_ARGS="-no-color" CHECKPOINT_DISABLE=1
{ terraform version | head -1; tofu version | head -1; } | tee "$out/versions.txt"

for module in aca aks; do
  echo "== terraform: $module"
  ( cd "modules/$module" && terraform init -input=false > "$out/$module-init.txt" 2>&1 && terraform validate > "$out/$module-validate.txt" 2>&1 \
    && terraform test 2>&1 | tee "$out/$module-terraform-test.txt"; exit "${PIPESTATUS[0]}" ) || { status=1; tail -n 60 "$out/$module-validate.txt" 2>/dev/null; }
  echo "== opentofu: $module"
  work="$(mktemp -d)"
  cp -r "modules/$module/." "$work/" && rm -rf "$work/.terraform"
  sed -i 's|registry.terraform.io|registry.opentofu.org|; /^  hashes = \[/,/^  \]/d' "$work/.terraform.lock.hcl"
  ( cd "$work" && tofu init -input=false > "$out/$module-tofu-init.txt" 2>&1 && tofu test 2>&1 | tee "$out/$module-tofu-test.txt"; exit "${PIPESTATUS[0]}" ) || { echo "tofu: FAILED" | tee -a "$out/$module-tofu-test.txt"; status=1; }
done

python measure.py modules/aca modules/aks | tee "$out/measure.txt"
( cd decision && python test_decide.py ) | tee "$out/decision-tests.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1
python decision/decide.py decision/requirements-example.json | tee "$out/decision-example.txt"
exit $status
