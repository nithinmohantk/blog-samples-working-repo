# LlamaIndex: production RAG sample

Sample for the dataa.dev article [LlamaIndex: The Data Framework for Building Production RAG Applications](https://www.dataa.dev/2025/04/15/llamaindex-the-data-framework-for-building-production-rag-applications/).

Pinned to the packages on PyPI on 15 April 2025 (`llama-index-core` 0.12.30). The data in `data/` is
synthetic: Larkfield Analytics, its product and its people are invented.

| File | What it shows |
| --- | --- |
| `rag/settings.py` | Azure OpenAI with Microsoft Entra ID (no keys) or OpenAI; timeouts and retries |
| `rag/ingest.py` | Loading, chunking, embedding; upserts into Chroma or Qdrant with a document store, so unchanged files are not re-embedded |
| `rag/engines.py` | Query engine, router over vector / summary / property graph indexes, chat engine with memory, `FunctionAgent`, sub-question engine |
| `rag/safe_calc.py` | Arithmetic tool for the agent without `eval()` |
| `rag/evaluate.py` | Faithfulness, relevancy and correctness judges plus string checks |
| `run.py` | Runs every example and records timings in `results/` |

## Run it

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements.lock
python -m pytest -q                       # 13 offline tests, no model calls

# Azure OpenAI: creates one resource group with a budget alert; delete it with ./teardown.sh
SUBSCRIPTION=<subscription> ./setup.sh
set -a; . ./.env; set +a
python run.py all

# or OpenAI
export RAG_PROVIDER=openai OPENAI_API_KEY=...   # OPENAI_CHAT_MODEL defaults to gpt-4o
python run.py all
```

## What was verified

The offline tests cover the calculator (including refusing `__import__`), document metadata,
chunking, re-ingestion into Chroma and local Qdrant (unchanged files write 0 nodes; an edited file
is re-embedded), the string check and configuration errors.

The live run on 25 November 2026 used Azure OpenAI with gpt-4.1-mini and text-embedding-3-small;
every example ran and the six evaluation questions passed all judges. Results:
[`examples/results.txt`](examples/results.txt). The OpenAI provider path was not run (no OpenAI key).
gpt-4o could not be deployed on the test subscription (zero quota in every region checked).
