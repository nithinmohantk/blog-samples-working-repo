# Part 3: server-side tools and API version 2026-10-21

Sample code for the dataa.dev series on agentic integration with the Claude API, Part 3 (27 October 2026).

The Part 1 prescription assistant, moved to `anthropic` 2.3.0 (which sends API version `2026-10-21`), with two server tools added: web search and web fetch, restricted to medicines regulators, so staff can ask whether there is a safety communication about a prescribed medicine. Anthropic runs these tools; the loop only sees each call after it has run.

| File | What it does |
| :--- | :--- |
| `rxagent/rx_service.py` | The same synthetic e-prescription back end as Parts 1 and 2 |
| `rxagent/tools.py` | Client tools (unchanged) and the server tool policy: `web_search_20260318` and `web_fetch_20260318`, `allowed_domains` = hpra.ie and ema.europa.eu, `allowed_callers=["direct"]`, `max_uses`, `url_sources` that exclude client tool results |
| `rxagent/loop.py` | The Part 1 loop plus: `pause_turn` resumption with a cap, deferred server calls in mixed batches, an after-the-fact audit of every server call with an identifier screen that stops the task, citations, and per-search cost |
| `rxagent/__main__.py` | Command line: prints each turn's server and client tool calls, searches, fetches, cost, the answer and its sources |
| `tests/` | 17 offline tests, including a wire test of the 2026-10-21 request (version header, `Authorization: Bearer`, no sampling parameters) |

## What moving from anthropic 1.x to 2.x changed for this code

| Change in 2.0.0 / API 2026-10-21 | Effect here |
| :--- | :--- |
| `anthropic-version: 2026-10-21` sent by default | None in the loop; the wire test asserts the new header |
| `temperature`, `top_p`, `top_k` rejected with a 400, even at default values | None: Part 1 never sent them |
| API key sent as `Authorization: Bearer` instead of `X-Api-Key` | Check proxies, gateways and log filters that look for `X-Api-Key` |
| `MessageParam(...)` can no longer be called | None: messages are plain dicts |
| `client.models.list(betas=...)` removed | Not used |

## Run

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q                       # offline, no API key needed
export ANTHROPIC_API_KEY=...                        # a workspace key with a spend limit
.venv/bin/python -m rxagent "Is there any current safety communication about the medicine on RX-1003?"
.venv/bin/python -m rxagent --no-server-tools "What is the status of RX-1002, and has it been dispensed?"
```

A key that can act on more than one workspace also needs `ANTHROPIC_WORKSPACE_ID`. Web search must be enabled for the organisation, and web fetch must not be turned off on the Console's Capabilities page.

All data is synthetic. Do not point this sample at real patient records.
