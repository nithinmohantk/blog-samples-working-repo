# Crash, checkpoint, resume: durable agent state

Sample for the dataa.dev article "[Crash, Checkpoint, Resume: Durable Agent State in LangGraph, Agent Framework and ADK](https://www.dataa.dev/2026/03/24/crash-checkpoint-resume-durable-agent-state/)".

One agent places an order with three tools that have side effects: reserve stock, charge a card, send a
confirmation. The lab kills the agent process with SIGKILL at three points around the charge, recovers it
the way each framework allows, and counts from a ledger how many times each effect happened.

The model is a scripted stand-in on 127.0.0.1. No hosted model and no cloud service is called.

| Path | What it is |
| --- | --- |
| `lab/standin.py` | The model stand-in. Stateless: it asks for the first tool that has no result in the conversation it is sent |
| `lab/tools.py` | The three tools, plain and idempotent, the ledger, and the crash points |
| `lab/agents/langgraph_agent.py` | LangGraph agent with a SQLite checkpointer |
| `lab/agents/agent_framework_agent.py` | Agent Framework agent with a file-backed history provider |
| `lab/agents/adk_agent.py` | ADK agent with a SQLite session service and resumability on |
| `lab/run.py` | Runs every case: three frameworks, three crash points, their recovery actions, two tool versions |
| `tests/run.py` | 10 unit tests for the stand-in and the tools |
| `requirements/` | One pinned requirements file per framework |

## Run

    ./ci.sh out      # Python 3.13; builds three virtual environments with uv

## What was verified

GitHub Actions, `ubuntu-latest`, Python 3.13: LangGraph 1.1.3 with langchain 1.2.13 and
langgraph-checkpoint-sqlite 3.0.3; Agent Framework 1.0.0rc5 (a release candidate); Google ADK 1.27.2;
dependencies resolved as of 23 March 2026. Transcripts and JSON for the latest run are on the
`ci-results-agent-crash-resume` branch.

## What this does not show

- A real model. The stand-in follows one plan and always asks for the first tool without a result. A real
  model may notice an interrupted step, ask the user, or do something else.
- Other persistence back ends. Each framework is tested with one durable store on local disk.
- Agent Framework workflows, which have their own checkpoint storage. Only the single agent is tested.
- Partial failures of the store itself, concurrent recoveries, or a crash during a checkpoint write.
- An effect and its ledger entry are one file append here. In a real system the effect is a call to another
  service, and the idempotency key has to be honoured by that service.
