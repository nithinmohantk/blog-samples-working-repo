#!/usr/bin/env bash
# Runs every check for the article against the cluster from setup.sh.
# Output goes to results/*.txt and to the terminal.
set -uo pipefail
cd "$(dirname "$0")" || exit 1
export PATH="$HOME/bin:$PATH"
REGION="${REGION:-eu-west-1}"
BATCH="${BATCH:-10}"
R=results
mkdir -p "$R"
NS=sbx
k() { kubectl -n "$NS" "$@"; }
section() { echo; echo "=== $1 ==="; }
wait_ready() { k wait --for=condition=Ready "$@" --timeout=600s >/dev/null; }
node_of() { k get pod "$1" -o jsonpath='{.spec.nodeName}'; }
node_info() { # pod -> instance type, kernel, threads per core
  local n it
  n=$(node_of "$1")
  it=$(kubectl get node "$n" -o jsonpath='{.metadata.labels.node\.kubernetes\.io/instance-type}')
  echo "node=$n instance=$it threads_per_core=$(aws ec2 describe-instance-types --region "$REGION" --instance-types "$it" --query 'InstanceTypes[0].VCpuInfo.DefaultThreadsPerCore' --output text) node_kernel=$(kubectl get node "$n" -o jsonpath='{.status.nodeInfo.kernelVersion}') container_runtime=$(kubectl get node "$n" -o jsonpath='{.status.nodeInfo.containerRuntimeVersion}')"
}

{
section "00 versions"
kubectl version 2>/dev/null | sed -n '1,3p'
eksctl version 2>/dev/null
aws --version
date -u +"run started %Y-%m-%dT%H:%M:%SZ"
section "00 runtime classes"
kubectl get runtimeclass isolated-sandbox -o yaml | grep -vE 'creationTimestamp|resourceVersion|uid:|managedFields|generation'
} 2>&1 | tee "$R/00-environment.txt"

{
section "01 kernel: plain vs sandboxed"
k apply -f manifests/pair.yaml >/dev/null
wait_ready pod/plain pod/sandboxed
for p in plain sandboxed; do
  echo "--- $p ($(k get pod $p -o jsonpath='{.spec.runtimeClassName}'))"
  node_info "$p"
  k exec "$p" -- sh -c 'echo pod_kernel=$(uname -r) nproc=$(nproc) mem_total_kib=$(grep MemTotal /proc/meminfo | tr -s " " | cut -d" " -f2)'
done
} 2>&1 | tee "$R/01-kernel.txt"

{
section "02 privileged + hostPID + hostPath /"
k apply -f manifests/host-access.yaml >/dev/null
wait_ready pod/escape-plain pod/escape-sandboxed
for p in escape-plain escape-sandboxed; do
  echo "--- $p"
  k exec "$p" -- sh -c '
    echo "pid 1 is: $(cat /proc/1/comm)"
    echo "processes visible: $(ls -d /proc/[0-9]* | wc -l)"
    echo "kubelet process visible: $(cat /proc/[0-9]*/comm 2>/dev/null | grep -c "^kubelet$")"
    echo "/host os: $(grep ^PRETTY_NAME /host/etc/os-release 2>&1)"
    echo "/host kubelet pod dirs: $(ls /host/var/lib/kubelet/pods 2>/dev/null | wc -l)"
    echo "/host top level: $(ls /host | tr "\n" " ")"'
done
} 2>&1 | tee "$R/02-host-access.txt"

imds='T=$(curl -s -m 3 -X PUT http://169.254.169.254/latest/api/token -H "X-aws-ec2-metadata-token-ttl-seconds: 60");
  echo "imdsv2 token: $([ -n "$T" ] && echo received || echo none)";
  for p in placement/region placement/availability-zone-id instance-id iam/security-credentials/; do
    echo "  $p -> HTTP $(curl -s -m 3 -o /dev/null -w "%{http_code}" -H "X-aws-ec2-metadata-token: $T" http://169.254.169.254/latest/meta-data/$p)"; done;
  echo "  imdsv1 (no token) -> HTTP $(curl -s -m 3 -o /dev/null -w "%{http_code}" http://169.254.169.254/latest/meta-data/placement/region)"'
{
section "03 instance metadata and credentials"
for p in plain sandboxed; do echo "--- $p"; k exec "$p" -- sh -c "$imds"; done
k apply -f manifests/credentials.yaml >/dev/null
wait_ready pod/podid-sandboxed
echo "--- podid-sandboxed (EKS Pod Identity)"
k exec podid-sandboxed -- sh -c 'aws --version; echo "AWS_CONTAINER_CREDENTIALS_FULL_URI=$AWS_CONTAINER_CREDENTIALS_FULL_URI"; aws sts get-caller-identity --query Arn --output text' \
  | sed -E 's/[0-9]{12}/<account>/g'
} 2>&1 | tee "$R/03-credentials.txt"

net='echo "interfaces: $(ls /sys/class/net | tr "\n" " ")"; echo "https to aws.amazon.com: $(curl -s -m 5 -o /dev/null -w "%{http_code}" https://aws.amazon.com || echo failed)"'
{
section "04 network-isolated annotation"
k apply -f manifests/network-isolated.yaml >/dev/null
wait_ready pod/no-network
echo "--- sandboxed (normal)"; k exec sandboxed -- sh -c "$net"
echo "--- no-network"; k exec no-network -- sh -c "$net"
section "05 annotation on Deployment metadata vs pod template"
k apply -f manifests/deployment-annotations.yaml >/dev/null
k rollout status deploy/wrong-place --timeout=600s >/dev/null
k rollout status deploy/right-place --timeout=600s >/dev/null
for d in wrong-place right-place; do
  echo "--- $d"; k exec deploy/$d -- sh -c "$net"
done
} 2>&1 | tee "$R/04-network-isolation.txt"

{
section "06 pod start time, $BATCH pods each, nodes already warm"
echo "nodes before: $(kubectl get nodes --no-headers | wc -l)"
for kind in plain sandboxed; do
  rc=""; [ "$kind" = sandboxed ] && rc="  runtimeClassName: isolated-sandbox"
  for i in $(seq 1 "$BATCH"); do cat <<EOF
apiVersion: v1
kind: Pod
metadata: {name: start-$kind-$i, namespace: $NS, labels: {batch: start-$kind}}
spec:
$rc
  containers:
  - name: main
    image: public.ecr.aws/amazonlinux/amazonlinux:2023
    command: ["sleep", "infinity"]
    resources: {requests: {cpu: 100m, memory: 256Mi}, limits: {cpu: 500m, memory: 256Mi}}
---
EOF
  done | k apply -f - >/dev/null
  k wait --for=condition=Ready pod -l batch=start-$kind --timeout=900s >/dev/null
  k get pods -l batch=start-$kind -o json | jq -r --arg kind "$kind" '
    [.items[] | {node: .spec.nodeName,
      s: ((.status.conditions[] | select(.type=="Ready") | .lastTransitionTime | fromdate)
          - (.metadata.creationTimestamp | fromdate))}] as $p
    | ($p | map(.s) | sort) as $s
    | "\($kind): n=\($s|length) min=\($s[0])s median=\($s[(($s|length)/2|floor)])s max=\($s[-1])s nodes=\($p|map(.node)|unique|length)"'
done
echo "nodes after: $(kubectl get nodes --no-headers | wc -l)"
k delete pod -l 'batch in (start-plain,start-sandboxed)' --wait=false >/dev/null
} 2>&1 | tee "$R/06-start-time.txt"

{
section "07 throughput to a plain iperf3 server (20 s, first 5 s omitted)"
k apply -f manifests/throughput.yaml >/dev/null
wait_ready pod/iperf-server pod/iperf-plain pod/iperf-sbx-default pod/iperf-sbx-raised
for p in iperf-plain iperf-sbx-default iperf-sbx-raised; do
  until k exec "$p" -- sh -c 'command -v iperf3' >/dev/null 2>&1; do sleep 3; done
done
until k exec iperf-plain -- iperf3 -c iperf-server -t 1 >/dev/null 2>&1; do sleep 3; done
echo "server on: $(node_of iperf-server)"
for p in iperf-plain iperf-sbx-default iperf-sbx-raised; do
  out=$(k exec "$p" -- iperf3 -c iperf-server -t 20 -O 5 -J)
  echo "$p on $(node_of $p): $(echo "$out" | jq -r '"sent \(.end.sum_sent.bits_per_second/1e6|floor) Mbps, received \(.end.sum_received.bits_per_second/1e6|floor) Mbps, retransmits \(.end.sum_sent.retransmits)"')"
done
} 2>&1 | tee "$R/07-throughput.txt"

date -u +"run finished %Y-%m-%dT%H:%M:%SZ" | tee -a "$R/07-throughput.txt"
echo; echo "ALL RESULTS:"; cat "$R"/*.txt > "$R/all.txt"; echo "results/all.txt written"
