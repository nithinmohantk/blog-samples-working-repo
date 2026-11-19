# context-budget

Companion code for the dataa.dev article *Token Budgets for LLM Prompts: Allocate the Context Window Before You Fill It* (5 June 2024).

`budget.py` plans a request against a model's context window:

1. reserve space for the model's output;
2. place the parts that must be sent whole (system prompt, tool definitions, the user's question) and fail clearly if they do not fit;
3. give each flexible section its minimum, then share the rest by weight, respecting maximums;
4. pack each section in its own order: newest turns first for conversation history (sent back in chronological order), highest score first for retrieved passages;
5. report tokens used per section, items dropped and headroom.

Token counting is injected, so use the tokenizer of the model you call (for example tiktoken's `o200k_base` for GPT-4o, `cl100k_base` for GPT-4 Turbo). Chat formats add a few framing tokens per message; pass your provider's figure as `per_message_overhead`.

```python
import tiktoken
from budget import Item, Section, plan

enc = tiktoken.get_encoding("o200k_base")
count = lambda t: len(enc.encode(t))

p = plan(
    window=128_000, output_reserve=4_096,
    fixed=[system_prompt, user_question],
    flexible=[
        Section("history", [Item(t, order=i) for i, t in enumerate(turns)], weight=1, min_tokens=2_000, keep="newest"),
        Section("passages", [Item(p.text, score=p.score) for p in hits], weight=3, keep="best"),
    ],
    count=count, per_message_overhead=3,
)
```

## Tests

```bash
pip install pytest==8.2.1
python -m pytest -q
```

8 tests with a whitespace token counter: output reserve and fixed parts, newest-turn selection in chronological order, best-score selection, weights and minimums, maximums with spare space redistributed, per-message overhead, and errors when fixed content or minimums cannot fit. Tested with Python 3.12; no dependencies.
