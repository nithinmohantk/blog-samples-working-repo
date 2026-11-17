#!/usr/bin/env bash
# Everything the workflow runs. Usage: ./ci.sh <output directory>
# Needs Go 1.21.5, gcc, Docker with QEMU for arm64, Terraform 1.6.6 and Python 3.12. Nothing is deployed.
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
status=0
AS_OF="2024-01-05"   # base images pinned to the newest dated tag on or before this day

go_tag="$(python tools/pick_image.py lambda/go 1 "$AS_OF")" || exit 2
al2023_tag="$(python tools/pick_image.py lambda/provided al2023 "$AS_OF")" || exit 2
GO_IMAGE="public.ecr.aws/lambda/go:$go_tag"
AL2023_IMAGE="public.ecr.aws/lambda/provided:$al2023_tag"
docker pull -q --platform linux/amd64 "$GO_IMAGE" > /dev/null || exit 2
docker pull -q --platform linux/amd64 "$AL2023_IMAGE" > /dev/null || exit 2
docker pull -q --platform linux/arm64 "$AL2023_IMAGE" > /dev/null || exit 2
{
  echo "go1.x image            $GO_IMAGE"
  echo "provided.al2023 image  $AL2023_IMAGE"
  echo "glibc in go1.x image   $(docker run --rm --platform linux/amd64 --entrypoint /bin/sh "$GO_IMAGE" -c 'ldd --version | head -1')"
  echo "glibc in al2023 image  $(docker run --rm --platform linux/amd64 --entrypoint /bin/sh "$AL2023_IMAGE" -c 'ldd --version 2>&1 | head -1' || echo 'no ldd')"
  echo "glibc on the runner    $(ldd --version | head -1)"
  go version; terraform version | head -1; python --version; docker --version
} | tee "$out/versions.txt"

echo "== unit tests"
(cd function && go mod tidy && go vet ./... && go test -count=1 ./...) 2>&1 | tee "$out/go-test.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1
cp function/go.sum "$out/go.sum"
(cd function && go list -m all) > "$out/go-modules.txt"

echo "== builds"
tools/build.sh "$PWD/dist" 2>&1 | tee "$out/build.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1
cp dist/build.tsv dist/buildinfo.txt "$out/"

echo "== in the Lambda runtime emulator"
python -u tools/emulate.py "$PWD/dist" "$GO_IMAGE" "$AL2023_IMAGE" "$out" 2>&1 | tee "$out/emulator.txt"
[ "${PIPESTATUS[0]}" -eq 0 ] || status=1

echo "== finder against moto"
python -m pytest -q finder/tests 2>&1 | tee "$out/finder-tests.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1

echo "== terraform validate"
(cd infra && terraform init -backend=false -input=false -no-color > /dev/null && terraform validate -no-color) \
  2>&1 | tee "$out/terraform.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1

rm -rf dist
exit $status
