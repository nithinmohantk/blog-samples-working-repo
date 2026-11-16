# The context cost of MCP tools

Sample for the dataa.dev article "[The Context Cost of MCP Tools: Tokens per Server, per Tool, and What Deferred Loading Saves](https://www.dataa.dev/2026/03/05/the-context-cost-of-mcp-tools/)".

Every tool definition an agent is given is sent to the model again on every request. This folder installs
nine widely used MCP servers at pinned versions, reads each one's tool listing, and counts what those
definitions cost in tokens: per server, per tool, per session, and after three kinds of reduction and two
kinds of deferred loading.

No tool is ever called, and no model is called. Each server is started as a local process on stdio and
asked only for its listing.

| Path | What it is |
| --- | --- |
| `servers.json` | The servers and versions measured |
| `measure/listing.py` | Starts a server and reads its tool listing |
| `measure/tokens.py` | Counts name, description and schema tokens with `o200k_base` and `cl100k_base` |
| `measure/slim.py` | Three reduction levels: strip generated fields, first-sentence descriptions, names and types only |
| `measure/search.py` | A BM25 tool index with a search tool, and a catalogue with load-by-name |
| `tasks.json` | Sixty-nine hand-written requests, each with the tool that should answer it |
| `lab/collect.py`, `lab/analyse.py` | Collect the listings, then produce every number in the article |
| `tests/run.py` | 13 unit tests |

## Run

    GH_TOKEN=<any token that can read public releases> ./ci.sh out      # Python 3.13 and Node.js 22

Without `GH_TOKEN` the GitHub server is skipped and everything else runs.

## What was verified

GitHub Actions, `ubuntu-latest`: MCP Python SDK 1.26.0, tiktoken 0.12.0, the server versions listed in
`servers.json`, GitHub MCP server v0.31.0, dependencies resolved as of 4 March 2026. Transcripts and JSON
for the latest run are on the `ci-results-mcp-context-cost` branch.

## What this does not show

- Billed tokens. Each provider wraps tool definitions in its own framing and uses its own tokeniser, so the
  figure on an invoice differs from these counts. The ranking and the size of the savings carry over.
- What a model does with a shortened description or a deferred tool. No model is called, so the effect of
  each reduction on tool selection is not measured.
- Search quality with a better retriever, or with queries written by a model. The index here is keyword
  matching, and the tasks are phrased the way a person would ask.
- Tool results, which also consume context and are often larger than the definitions.
- Servers configured differently. The GitHub server is measured with its default toolsets and with all of
  them; the Playwright server with its default capabilities.
