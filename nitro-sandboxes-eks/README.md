# AWS Nitro Sandboxes on Amazon EKS: what changes for a pod

Sample for the dataa.dev article on AWS Nitro Sandboxes on Amazon EKS (isolated mode).
It puts the same pods on the node's shared kernel and in a Nitro Sandbox and compares
them: kernel, what a privileged pod can reach on the node, instance metadata and
credentials, network isolation, where annotations must go, start time and throughput.

| File | What it does |
| --- | --- |
| `setup.sh` | Budget alert, EKS Auto Mode cluster (Kubernetes 1.37), IAM role and Pod Identity association |
| `run-tests.sh` | Runs every check and writes `results/*.txt` |
| `teardown.sh` | Deletes everything and lists anything left over |
| `manifests/pair.yaml` | The same pod plain and sandboxed |
| `manifests/host-access.yaml` | Privileged pod with `hostPID` and the node's `/` mounted |
| `manifests/credentials.yaml` | Sandboxed pod that calls STS with EKS Pod Identity |
| `manifests/network-isolated.yaml` | Sandbox booted with no network device |
| `manifests/deployment-annotations.yaml` | The annotation on the Deployment vs on the pod template |
| `manifests/throughput.yaml` | iperf3 server and three clients (plain, default throttles, raised) |

## Run it

In AWS CloudShell (it has the AWS CLI, kubectl and jq; `setup.sh` installs eksctl):

```bash
git clone https://github.com/nithinmohantk/blog-samples-working-repo.git
cd blog-samples-working-repo/nitro-sandboxes-eks
EMAIL=you@example.com ./setup.sh     # about 20 minutes
./run-tests.sh                       # about 15 minutes
./teardown.sh                        # about 15 minutes
```

Defaults: `REGION=eu-west-1`, `CLUSTER=nitro-sbx-blogtest`, `BUDGET=20` (USD, alert at 50%).
Costs while it runs: the EKS control plane, the Auto Mode nodes (EC2 plus the Auto Mode
fee) and the NAT gateway eksctl creates. Nitro Sandboxes themselves have no extra charge.

Not covered: confidential mode, attestation and AWS KMS key policies.

## What was verified

One run on 26 November 2026 in AWS CloudShell, eu-west-1, Kubernetes 1.37.1 on EKS Auto Mode
(eksctl 0.232.0). The output is in `results/run-2026-11-26.txt`. Sections 00 to 06 ran; the
throughput check (07) did not finish, so no throughput figures were measured. The first run of
sections 04 to 06 stalled while pods waited for nodes; `run-tests.sh` now waits in shorter slices
and frees nodes before the start-time batch. Teardown left no cluster, instance, NAT gateway,
Elastic IP, VPC or IAM role behind.
