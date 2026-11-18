#!/usr/bin/env bash
# Everything the workflow runs. Usage: ./ci.sh <output directory>
# Needs Docker, kind v0.22.0, kubectl and Python 3.12 with PyYAML and pytest.
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
status=0
# kind v0.22.0's default node image (pkg/apis/config/defaults/image.go at the v0.22.0 tag)
NEW_IMAGE="kindest/node:v1.29.2@sha256:51a1434a5397193442f0be2a297b488b6c919ce8a3931be0ce822606ea5ca245"

{
  echo "runner: $(nproc) vCPU"
  kind version
  kubectl version --client
  docker --version
  python --version
  python -c 'import importlib.metadata as m; [print(p, m.version(p)) for p in ("pyyaml", "pytest")]'
} > "$out/environment.txt" 2>&1

echo "== unit tests"
python -m pytest -q tests 2>&1 | tee "$out/unit-tests.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1

docker pull -q busybox:1.36.1 >/dev/null

echo "== Kubernetes 1.29: every scenario"
kind create cluster --name sidecars --image "$NEW_IMAGE" --wait 120s > "$out/kind-1.29.txt" 2>&1 || status=1
kind load docker-image busybox:1.36.1 --name sidecars >> "$out/kind-1.29.txt" 2>&1
python sidecars/run.py --label v1.29 --node sidecars-control-plane --out "$out/results.json" \
  2>&1 | tee "$out/run-1.29.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1
kubectl get --raw /metrics 2>/dev/null | grep 'kubernetes_feature_enabled{name="SidecarContainers"' > "$out/feature-gate-1.29.txt"
kind delete cluster --name sidecars >/dev/null 2>&1

echo "== Kubernetes 1.28: the native sidecar Job where the feature gate is off by default"
for tag in v1.28.7 v1.28.6; do
  if kind create cluster --name old --image "kindest/node:$tag" --wait 120s > "$out/kind-1.28.txt" 2>&1; then
    echo "node image: $(docker inspect --format '{{index .RepoDigests 0}}' "kindest/node:$tag")" >> "$out/kind-1.28.txt"
    break
  fi
done
kind load docker-image busybox:1.36.1 --name old >> "$out/kind-1.28.txt" 2>&1
python sidecars/run.py --label v1.28 --node old-control-plane --only native-on-old --out "$out/results.json" \
  2>&1 | tee "$out/run-1.28.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1
kubectl get --raw /metrics 2>/dev/null | grep 'kubernetes_feature_enabled{name="SidecarContainers"' > "$out/feature-gate-1.28.txt"
kind delete cluster --name old >/dev/null 2>&1

python sidecars/report.py "$out/results.json" | tee "$out/summary.txt" || status=1
exit $status
