# Kubernetes 1.29 native sidecars

Sample code for the dataa.dev article *Kubernetes 1.29 Native Sidecars: Jobs That Finish, Ordered Shutdown and the 1.28 Trap*.

Seven scenarios on kind clusters, each a small manifest in `manifests/`. The harness applies one, waits,
reads container states from the API and, for the two shutdown scenarios, an event log the containers
write to the node with `/proc/uptime` timestamps (one clock for every container, centisecond resolution).

## What is here

| Path | What it does |
| --- | --- |
| `manifests/job-classic-sidecar.yaml` | A Job with the log shipper as an ordinary second container. |
| `manifests/job-native-sidecar.yaml` | The same Job with the log shipper as an init container with `restartPolicy: Always`. |
| `manifests/pod-startup-order.yaml` | A sidecar with a startup probe that passes after 8 seconds. |
| `manifests/pod-termination-order.yaml` | Two sidecars and a main container; each logs SIGTERM and exit. |
| `manifests/pod-grace-squeeze.yaml` | Main ignores SIGTERM for the whole grace period; the sidecar wants 5 s to flush. |
| `manifests/job-sidecar-crash.yaml` | A sidecar that exits with an error in a Job whose Pod `restartPolicy` is `Never`. |
| `sidecars/run.py` | Runs the scenarios against the current kubectl context. |
| `sidecars/analyse.py` | Parses pod status, watch streams and the event logs. |
| `tests/` | Unit tests for the parsing, and a check that every manifest's init containers are sidecars. |
| `ci.sh` | What CI runs: a 1.29.2 cluster for six scenarios, a 1.28.7 cluster for the last one. |

## Run it

```bash
pip install uv && uv pip install --exclude-newer 2024-02-16 pyyaml pytest
./ci.sh out    # needs Docker, kind v0.22.0 and kubectl; about 7 minutes
```

## What was verified

GitHub Actions, kind v0.22.0 (14 February 2024) with its default node image
`kindest/node:v1.29.2@sha256:51a1434a…ca245` and `kindest/node:v1.28.7@sha256:9bc6c451…65c58`, kubectl v1.29.2,
busybox 1.36.1, Python 3.12 with PyYAML 6.0.1 and pytest 8.0.1:

```text
[v1.29/job-classic] server v1.29.2
  job_condition: none after 60 s
  seconds_to_condition: None
  pod_phase: Running
  log-shipper     main reason=None exit=None restarts=0
  main            main reason=Completed exit=0 restarts=0
[v1.29/job-native] server v1.29.2
  job_condition: Complete
  seconds_to_condition: 40.3
  pod_phase: Succeeded
  log-shipper     init reason=Error exit=137 restarts=0
  main            main reason=Completed exit=0 restarts=0
[v1.29/startup-order] server v1.29.2
  main_started_after_proxy_s: 9.0
  proxy           init reason=None exit=None restarts=0
  main            main reason=None exit=None restarts=0
[v1.29/termination-order] server v1.29.2
  delete_returned_after_s: 6.0
    0.00s  main            TERM
    3.01s  main            exit
    3.05s  second-sidecar  TERM
    4.05s  second-sidecar  exit
    4.09s  first-sidecar   TERM
    5.09s  first-sidecar   exit
  final first-sidecar   exit=0 reason=Completed
  final second-sidecar  exit=0 reason=Completed
  final main            exit=0 reason=Completed
[v1.29/grace-squeeze] server v1.29.2
  delete_returned_after_s: 13.0
    0.00s  main            TERM-ignored
   10.00s  log-shipper     TERM
  final log-shipper     exit=137 reason=Error
  final main            exit=137 reason=Error
[v1.29/sidecar-crash] server v1.29.2
  job_condition: Complete
  seconds_to_condition: 29.7
  pod_phase: Succeeded
  log-shipper     init reason=Error exit=1 restarts=2
  main            main reason=Completed exit=0 restarts=0
[v1.28/native-on-old] server v1.28.7
  pod_phase: Pending
  stored_restartPolicy: (field dropped)
  job_condition_after_45s: None
  log-shipper     init reason=None exit=None restarts=0
  main            main reason=PodInitializing exit=None restarts=0
```

## What was not verified

- kind only, one node. No managed service (EKS, AKS, GKE) and no mixed-version cluster where the control
  plane and the kubelets run different minor versions.
- No service mesh or sidecar injector. Injectors that add containers to `containers` do not get the new behaviour.
- busybox shell loops stand in for real log shippers and proxies.
