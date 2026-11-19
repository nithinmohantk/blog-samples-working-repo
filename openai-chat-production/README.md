# openai-chat-production

Sample code for the dataa.dev article *OpenAI Chat Completions in September 2024: Snapshots, Strict Tool Calls, Structured Outputs, Streaming and Batch* (10 Sep 2024).

`basics.py` covers a first call, a multi-turn `Conversation` that resends a capped history, and image input from a URL or a local file (`image_part`, `describe_image`).

`chat_api.py` shows how to call the OpenAI Chat Completions API from Python as of September 2024:

- `make_client` – explicit timeout (the SDK default is 10 minutes) and retries for connection errors, 408, 409, 429 and 5xx.
- `MODEL` – a pinned snapshot, `gpt-4o-2024-08-06`, instead of the moving `gpt-4o` alias.
- `run_with_tools` – a tool-calling loop with strict schemas from Pydantic models, `parallel_tool_calls=False`, argument validation, errors returned to the model, and a step limit.
- `extract` – Structured Outputs into a Pydantic model, reporting `ok`, `refused`, `truncated` or `filtered`.
- `stream_text` – streaming with `stream_options={"include_usage": True}` so token usage is recorded.
- `batch_lines`, `submit_batch`, `read_batch_results` – Batch API input lines, submission and result parsing by `custom_id`.

## Run the tests

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q
```

The 13 tests use `httpx.MockTransport`, so no API key or network is needed. They check the request bodies (pinned model, strict tool schema, `parallel_tool_calls`, `json_schema` response format, `stream_options`), the tool loop's handling of invalid arguments, unknown tools, tool exceptions and step limits, refusal and truncation reporting, streamed usage, SDK retry on 429, batch result parsing, conversation history capping and image content parts.
