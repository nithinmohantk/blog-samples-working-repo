#!/usr/bin/env bash
# Downloads the two pinned CLIs and runs the experiment matrix. Usage: ./ci.sh <output directory>
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
TERRAFORM_VERSION="1.16.5"
TOFU_VERSION="1.13.1"
bin="$(mktemp -d)"
curl -fsSL -o "$bin/terraform.zip" "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip" && unzip -q -o "$bin/terraform.zip" -d "$bin/tf" || exit 2
curl -fsSL -o "$bin/tofu.zip" "https://github.com/opentofu/opentofu/releases/download/v${TOFU_VERSION}/tofu_${TOFU_VERSION}_linux_amd64.zip" && unzip -q -o "$bin/tofu.zip" -d "$bin/tofu" || exit 2
{ "$bin/tf/terraform" version; "$bin/tofu/tofu" version; sha256sum "$bin/terraform.zip" "$bin/tofu.zip" | sed "s|$bin/||"; } | tee "$out/versions.txt"
python run_matrix.py "$bin/tf/terraform" "$bin/tofu/tofu" "$out" | tee "$out/matrix.txt"
exit "${PIPESTATUS[0]}"
