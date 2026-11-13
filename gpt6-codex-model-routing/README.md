# GPT-6 in Codex: which model for which work, and what a session costs

Sample for the dataa.dev article "[GPT-6 in Codex: Choosing Between Astra, Sol and Luna](https://www.dataa.dev/2026/09/26/gpt-6-in-codex-choosing-between-astra-sol-and-luna/)".

Two things, neither of which calls a model or runs the Codex CLI:

* a cost model for the GPT-6 family built on the published prices: one request, the price step at 272,000
  input tokens, an agent session with and without prompt caching and compaction, and one piece of work split
  across the three models;
* an example `~/.codex/config.toml` with one model per kind of work, validated against the configuration schema
  that ships in the Codex repository at the tag for CLI 0.157.1.

The token counts in the sessions are assumptions, stated in `tests/run.py`. Change them to match your own usage
and the conclusions may change with them. The cost model also assumes the same token counts whichever model runs
a step, which the vendors say is not quite true and which only your own measurements can correct.

| Path | What it is |
| --- | --- |
| `prices.json` | Published prices and limits, with sources |
| `gpt6_cost/model.py` | Request cost, the long-context rule, the agent-session simulation, the cache break-even |
| `codex/config.toml` | The example configuration |
| `tests/run.py` | All checks |
| `ci.sh` | Fetches the schema by checksum, installs `jsonschema` as of 26 September 2026 and runs the checks |

## Run

    ./ci.sh out
