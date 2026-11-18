# GPT-6 in Codex: which model for which work, and what a session costs

Sample for the dataa.dev article "[GPT-6 in Codex: Choosing Between Astra, Sol and Luna](https://www.dataa.dev/2026/09/26/gpt-6-in-codex-choosing-between-astra-sol-and-luna/)".

Three things. None of them calls a model.

* A cost model for the GPT-6 family built on the published prices: one request, the price step at 272,000
  input tokens, an agent session with and without prompt caching and compaction, and one piece of work split
  across the three models.
* An example Codex configuration with one model per kind of work: `config.toml` and three profile files,
  validated against the configuration schema in the Codex repository.
* A harness that runs the real Codex CLI (0.157.1) against a local stand-in for the Responses API and records
  what the CLI sends: which model and effort each setting produces, how the prompt grows from step to step,
  what a subagent and a review look like, and what happens at the compaction limit.

The stand-in plays a script; it does not think. The CLI is given a provider that exists only on the machine
and a key that is not real, so it cannot reach a model. Commands the script asks for are run by Codex in its
read-only sandbox in a throwaway repository.

The token counts in the sessions are assumptions, stated in `tests/run.py`. Change them to match your own usage
and the conclusions may change with them. The cost model also assumes the same token counts whichever model runs
a step, which the vendors say is not quite true and which only your own measurements can correct.

| Path | What it is |
| --- | --- |
| `prices.json` | Published prices and limits, with sources |
| `gpt6_cost/model.py` | Request cost, the long-context rule, the agent-session simulation, the cache break-even |
| `codex/config.toml`, `codex/*.config.toml` | The example configuration and its three profiles |
| `harness/standin.py` | The scripted, streaming stand-in for `POST /v1/responses` |
| `harness/run.sh` | Installs the CLI, runs seven scenarios against the stand-in |
| `harness/report.py` | Summarises and checks what the CLI sent |
| `tests/run.py` | All checks |
| `ci.sh` | Fetches the schema by checksum, installs Python packages as of 26 September 2026, runs the checks and the harness |

## Run

    ./ci.sh out
