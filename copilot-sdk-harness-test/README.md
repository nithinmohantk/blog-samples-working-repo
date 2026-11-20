# Microsoft Copilot SDK 2.0 through the eleven-failure harness test

Sample code for the dataa.dev article on putting Microsoft Copilot SDK 2.0 to the test (20 November 2026).

The eleven bad days from [What an Agent Harness Needs Before Production](https://www.dataa.dev/2026/09/15/agent-harness-production-eleven-failures/), run against `microsoft-copilot-sdk` 2.0.1 (Python), in two configurations:

| Configuration | What it is |
| :--- | :--- |
| `defaults` | The README quick start: `mode="coding-agent"`, `PermissionHandler.approve_all`, `@define_tool` handlers |
| `hardened` | `mode="empty"` with per-tenant storage and an explicit tool allow-list, a permission gate for refunds and commands, a turn budget that aborts the session, tools wrapped with a 1 s timeout, retries with jitter, a 4,000-character cap and a safe error, and a refund keyed on the business operation. Generated-code scenarios use the runtime sandbox with the secret masked |

No real model is involved. `harness/scripted_model.py` is an OpenAI-compatible endpoint that misbehaves on cue, reached through the SDK's BYOK provider with Copilot inference switched off, so every scenario is exact, repeatable and free.

| File | What it does |
| :--- | :--- |
| `harness/scripted_model.py` | The scripted chat-completions endpoint, with a log of everything the runtime sent |
| `harness/shop.py` | Orders, a flaky carrier API, a slow stock service, a 2 MB export and an idempotent refund ledger |
| `harness/configs.py` | The two configurations: tools, permission gate, budget, guarded handlers, sandbox |
| `harness/scenarios.py` | Runs the scenarios and prints one verdict per run |
| `harness/crash_worker.py` | Scenario 11 in two processes: pay a refund and die, then resume from the session journal |
| `tests/test_eleven.py` | The scenarios as 11 tests |

## Run

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m copilot download-runtime --in-process     # about 200 MB, verified against SHA256SUMS
.venv/bin/python -m pytest -q                                 # about 2 minutes, no API key or GitHub sign-in
.venv/bin/python -m harness.scenarios                         # all scenarios, both configurations
```

The sandbox scenarios need `bwrap`, `slirp4netns` and `ip` on Linux (`apt-get install bubblewrap slirp4netns iproute2`). Without them the runtime refuses to run sandboxed commands, and the test is skipped.

The generated-code scenarios read a fake secret, `PAYMENTS_API_KEY=sk-test-NOT-A-REAL-KEY-1234`, that the runner puts in its own environment. Do not run them in a shell that holds real credentials.
