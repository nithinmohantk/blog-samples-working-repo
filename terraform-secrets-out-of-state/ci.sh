#!/usr/bin/env bash
# Downloads the two pinned CLIs, starts a local Secrets Manager emulator and runs the experiments.
# Usage: ./ci.sh <output directory>
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
TERRAFORM_VERSION="1.14.0"   # 19 November 2025
TOFU_VERSION="1.11.0"        # 9 December 2025
bin="$(mktemp -d)"
curl -fsSL -o "$bin/terraform.zip" "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip" && unzip -q -o "$bin/terraform.zip" -d "$bin/tf" || exit 2
curl -fsSL -o "$bin/tofu.zip" "https://github.com/opentofu/opentofu/releases/download/v${TOFU_VERSION}/tofu_${TOFU_VERSION}_linux_amd64.zip" && unzip -q -o "$bin/tofu.zip" -d "$bin/tofu" || exit 2
python -m pip install --quiet "moto[server]" boto3 || exit 2
{ "$bin/tf/terraform" version | head -1; "$bin/tofu/tofu" version | head -1; python --version; python -c "import moto, boto3; print('moto', moto.__version__, 'boto3', boto3.__version__)"; grep -h 'version *= *"' ephemeral/versions.tf | tr -s ' '; } | tee "$out/versions.txt"
export TF_PLUGIN_CACHE_DIR="$bin/plugins"; mkdir -p "$TF_PLUGIN_CACHE_DIR"
moto_server -H 127.0.0.1 -p 5000 > "$out/moto.log" 2>&1 & moto=$!
for i in $(seq 1 30); do curl -fsS http://127.0.0.1:5000/moto-api/ > /dev/null 2>&1 && break; sleep 1; done
python run_experiments.py "$bin/tf/terraform" "$bin/tofu/tofu" "$out" 2>&1 | tee "$out/experiments.txt"; status="${PIPESTATUS[0]}"
kill $moto 2>/dev/null
exit "$status"
