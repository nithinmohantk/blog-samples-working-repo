# k8s-138-upgrade-readiness

Static checks for the changes announced for Kubernetes v1.38 that need action
before an upgrade. Sample code for the dataa.dev article
"Kubernetes 1.38 Preview: Breaking Changes, Removals and an Upgrade Readiness Check".

The scanner reads files only. It does not connect to a cluster.

## Checks

| Check | Looks in | Reports |
| :--- | :--- | :--- |
| `K138-ENV` | any text file | `KUBECTL_REMOTE_COMMAND_WEBSOCKETS`, `KUBECTL_PORT_FORWARD_WEBSOCKETS` (removed from kubectl) |
| `K138-KUBERC` | `Preference` objects in `kubectl.config.k8s.io` | allowlist entries that use `name`; files still on `v1beta1` |
| `K138-CGROUPDRIVER` | `KubeletConfiguration` | `cgroupDriver` set explicitly |
| `K138-CGROUPV1` | `KubeletConfiguration` | `failCgroupV1: false` |
| `K138-WEBHOOK` | validating and mutating webhook configurations | rules that select authentication or authorization review resources |
| `K138-SWAP` | Pods and pod templates | pod-level memory request equal to the limit while a container can burst |

Severities: `ACTION` (change needed before or at the upgrade), `WARN` (review), `INFO`.

## Run

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m k138check fixtures/before
.venv/bin/python -m k138check fixtures/after
.venv/bin/python -m k138check path/to/manifests path/to/ci --format json --fail-on warn
```

Exit code 0 means no finding at or above `--fail-on` (default `action`), 1 means
at least one, 2 means the scan could not run.

To check live objects, export them first:

```bash
kubectl get validatingwebhookconfigurations,mutatingwebhookconfigurations -o yaml > webhooks.yaml
kubectl get pods -A -o yaml > pods.yaml
```

## What was verified

- 43 tests pass with Python 3.13, `pyyaml==6.0.3`, `pytest==9.0.2`.
- `fixtures/before` gives 3 action, 4 warn and 2 info findings; `fixtures/after` gives none.
- Field names, feature gates and the swap rule were read from the Kubernetes
  source at `master` commit `ce9710e5` (27 Nov 2026) and tag `v1.38.0-beta.0`,
  and from the v1.38 sneak peek of 23 Nov 2026.
- `ci.sh` runs in GitHub Actions (`.github/workflows/k8s-138.yml`) and publishes
  its output to the `ci-results-k8s-138` branch. Run of 28 Nov 2026: kind v0.33.0,
  Kubernetes v1.37.0, containerd 2.3.4, kubectl v1.37.3 and v1.38.0-beta.0.
  - `KUBECTL_REMOTE_COMMAND_WEBSOCKETS=false`: kubectl v1.37.3 used SPDY/3.1,
    kubectl v1.38.0-beta.0 ignored it and used WebSockets.
  - kuberc: v1.37.3 rejects a `v1` file (`no valid preferences found`);
    v1.38.0-beta.0 reads `v1beta1` with `name`, reads `v1` with `command`, and
    fails on `v1` with `name` (`empty allowlist entry #1`).
  - Server dry run of `fixtures/before/webhooks.yaml` on v1.37.0 returns one
    warning per named review resource and none for the wildcard rule.
  - `fixtures/before/report-worker.yaml` is accepted on v1.37.0; pods are `Burstable`.

## Limits

- Kubernetes v1.38.0 is not released yet (planned for 16 Dec 2026). The checks
  follow the announced changes and must be re-read against the final release notes.
- `LegacyCgroupDriverFallback` and the kubelet's rejection of `cgroupDriver`
  were announced in the sneak peek but were not in `master` at the commit above.
- No v1.38 control plane or kubelet was run. The swap and cgroup driver checks
  follow the announcement and the source.
- Helm templates are skipped until rendered (`helm template` first).
- `K138-SWAP` does not model the case where the pod-level memory request is
  left out and containers set their own requests.
- The scanner cannot tell which nodes use `LimitedSwap` or which container
  runtime version a node runs. Check those on the nodes.
