#!/usr/bin/env bash
# Runs the unit tests, the scanner, and a set of checks against a kind cluster
# with two kubectl clients (current stable minor and the v1.38 pre-release).
# Every step writes a file under the output directory. A step that fails is
# recorded and the script carries on, so one surprise does not hide the rest.
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
out="${1:?usage: ci.sh <output-dir>}"
k_new="${KUBECTL_NEW:?path to the v1.38 pre-release kubectl}"
k_old="${KUBECTL_OLD:?path to the stable kubectl}"
mkdir -p "$out"
cd "$here"
failures=0

record() { # record <file> <command...>: store output and exit code
  local file="$out/$1"; shift
  { echo "\$ $*"; "$@" 2>&1; echo "exit=$?"; } > "$file"
}

# 1. Unit tests and scanner
python -m pytest -q > "$out/pytest.txt" 2>&1 || failures=$((failures + 1))
python -m k138check fixtures/before > "$out/scan-before.txt" 2>&1
[ $? -eq 1 ] || failures=$((failures + 1))
python -m k138check fixtures/after > "$out/scan-after.txt" 2>&1 || failures=$((failures + 1))

# 2. Cluster and versions
kind create cluster --name k138 --wait 180s > "$out/kind-create.txt" 2>&1 || { echo "kind failed" >> "$out/kind-create.txt"; exit 1; }
{
  kind version
  echo "--- new client"; "$k_new" version --client
  echo "--- old client"; "$k_old" version --client
  echo "--- server";     "$k_old" version -o json | python -c 'import json,sys; print(json.load(sys.stdin)["serverVersion"]["gitVersion"])'
  echo "--- nodes";      "$k_old" get nodes -o wide
} > "$out/versions.txt" 2>&1

# 3. Feature gates as the API server reports them
"$k_old" get --raw /metrics 2>/dev/null \
  | grep '^kubernetes_feature_enabled' \
  | grep -E 'name="(PodLevelResources|ExcludeAdmissionWebhookVirtualResources|KubeletCgroupDriverFromCRI|EvictionRequestAPI|DRAPartitionableDevices|LegacyCgroupDriverFallback)"' \
  > "$out/feature-gates.txt" 2>&1

# 4. Kubelet's view of its cgroup settings
node="$("$k_old" get nodes -o jsonpath='{.items[0].metadata.name}')"
"$k_old" get --raw "/api/v1/nodes/$node/proxy/configz" \
  | python -c 'import json,sys; c=json.load(sys.stdin)["kubeletconfig"]; print(json.dumps({k: c.get(k) for k in ("cgroupDriver","failCgroupV1","memorySwap","failSwapOn")}, indent=1))' \
  > "$out/kubelet-configz.txt" 2>&1

# 5. kuberc: beta file, stable file, and a stable file that keeps the old key
sed '0,/command: aws/s//name: aws/' fixtures/after/kuberc > "$out/kuberc-v1-with-name"
for client in new old; do
  bin="$k_new"; [ "$client" = old ] && bin="$k_old"
  record "kuberc-$client-v1beta1-name.txt" "$bin" --kuberc fixtures/before/kuberc get namespaces default
  record "kuberc-$client-v1-command.txt"   "$bin" --kuberc fixtures/after/kuberc  get namespaces default
  record "kuberc-$client-v1-name.txt"      "$bin" --kuberc "$out/kuberc-v1-with-name" get namespaces default
done

# 6. Removed environment variables: which protocol does exec use?
"$k_old" run probe --image=registry.k8s.io/pause:3.10 --restart=Never > /dev/null 2>&1
"$k_old" wait --for=condition=Ready pod/probe --timeout=120s > /dev/null 2>&1
"$k_old" run shell --image=busybox:1.37.0 --restart=Never --command -- sleep 3600 > /dev/null 2>&1
"$k_old" wait --for=condition=Ready pod/shell --timeout=180s > /dev/null 2>&1
for client in new old; do
  bin="$k_new"; [ "$client" = old ] && bin="$k_old"
  for setting in unset false; do
    file="$out/exec-$client-websockets-$setting.txt"
    if [ "$setting" = false ]; then
      KUBECTL_REMOTE_COMMAND_WEBSOCKETS=false "$bin" exec shell -v=8 -- echo ok > "$file.raw" 2>&1; code=$?
    else
      "$bin" exec shell -v=8 -- echo ok > "$file.raw" 2>&1; code=$?
    fi
    {
      echo "exit=$code"
      echo "lines mentioning websocket: $(grep -ci 'websocket' "$file.raw")"
      echo "lines mentioning spdy: $(grep -ci 'spdy' "$file.raw")"
      grep -i -m 6 -E 'websocket|spdy' "$file.raw" | cut -c1-240
    } > "$file"
    rm -f "$file.raw"
  done
done

# 7. Webhook rules that name review resources: what does the API server say?
record "webhooks-dry-run.txt" "$k_old" apply --dry-run=server -f fixtures/before/webhooks.yaml

# 8. Pod-level resources: accepted, and which QoS class results?
"$k_old" create namespace reporting > /dev/null 2>&1
record "pod-level-apply.txt" "$k_old" apply -f fixtures/before/report-worker.yaml
sleep 8
{
  "$k_old" get pods -n reporting -o jsonpath='{range .items[*]}{.metadata.name}{" qosClass="}{.status.qosClass}{" podResources="}{.spec.resources}{"\n"}{end}'
} > "$out/pod-level-qos.txt" 2>&1

kind delete cluster --name k138 > /dev/null 2>&1
echo "failures=$failures" > "$out/summary.txt"
exit "$failures"
