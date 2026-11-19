# gpt-model-compare

Companion code for the dataa.dev article *GPT-3.5 Turbo, GPT-4 or GPT-4 Turbo: Choosing an OpenAI Model in January 2024* (15 January 2024).

| File | What it does |
| :--- | :--- |
| `models.py` | The OpenAI chat models available in January 2024 with context window, output cap, knowledge cutoff, price per 1K tokens and JSON-mode support; cost, fit and cheapest-model helpers. |
| `compare.py` | Runs the same prompts through several models with temperature 0 and a fixed `seed`, uses JSON mode where the model supports it, validates JSON answers, and prints latency, tokens, cost and `system_fingerprint` for each. |

## Use

```bash
pip install openai==1.7.2
# prompts.jsonl: {"id": "p1", "user": "...", "json": true}
OPENAI_API_KEY=... python compare.py prompts.jsonl gpt-3.5-turbo-1106 gpt-4-1106-preview
```

Prices in `models.py` are January 2024 list prices; check OpenAI's pricing page before relying on them.

## Tests

```bash
pip install openai==1.7.2 httpx==0.26.0 pydantic==2.5.3 pytest==7.4.4
python -m pytest -q
```

6 tests: cost arithmetic, context and output-cap checks, cheapest model that fits (with and without a JSON requirement), and `compare.py` against a mocked OpenAI API (httpx `MockTransport`) covering seed, temperature, JSON mode only where supported, invalid JSON and API errors. No real API calls. Tested with Python 3.12.
