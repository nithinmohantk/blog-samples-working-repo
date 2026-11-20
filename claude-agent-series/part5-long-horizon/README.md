# Part 5: a long-horizon agent on Claude Fable 5.2

Sample code for the dataa.dev series on agentic integration with the Claude API, Part 5 (9 November 2026).

An audit agent that works through 48 synthetic repeat prescriptions against four written rules and records findings in a register. The task takes dozens of tool calls, so the loop is built for length: an append-only history (Fable 5.2 enforces the thinking prefix check), on-demand compaction when the context passes a threshold you choose, a checkpoint after every turn so the run can resume, a cost budget, and a nudge when the model stops before the register says the work is done. Because the data is generated, every run is scored for precision and recall against an answer key.

| File | What it does |
| :--- | :--- |
| `auditagent/data.py` | The seeded dataset (48 prescriptions, 16 patients) and the answer key: 56 expected findings |
| `auditagent/service.py` | Read-only records, an append-only idempotent findings register, progress, checkpoint state |
| `auditagent/tools.py` | Five strict tools: `get_progress`, `list_prescriptions`, `get_details`, `record_findings`, `mark_reviewed` |
| `auditagent/loop.py` | The long-horizon loop: `compact-2026-09-04` compaction, checkpoints, budget, usage across `usage.iterations` |
| `auditagent/__main__.py` | Command line: runs, resumes, prints each turn and scores the register |
| `tests/` | 9 offline tests, including append-only history, compaction, resume and budget |

## Run

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q                                        # offline, no API key needed
export ANTHROPIC_API_KEY=...                                         # a workspace key with a spend limit
.venv/bin/python -m auditagent --model claude-fable-5-2 --stop-after 4   # start, then stop (simulated interruption)
.venv/bin/python -m auditagent --resume --results fable.json            # continue from state.json and score
.venv/bin/python -m auditagent --model claude-opus-5-5 --checkpoint opus.json --results opus.json
```

`--budget` (default $4) stops a run when its cost reaches the limit. Claude Fable 5.2 costs $8 per million input tokens and $40 per million output tokens, and requires 30-day data retention: it is not available under zero data retention. All data is synthetic. Do not point this sample at real patient records.
