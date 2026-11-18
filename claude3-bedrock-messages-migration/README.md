# Claude 3 on Bedrock: from Text Completions to the Messages API

Sample code for the dataa.dev article *Claude 3 on Amazon Bedrock: Moving from Text Completions to the Messages API*.

Claude 3 Sonnet (Bedrock, 4 March 2024) and Claude 3 Haiku (13 March 2024) accept only the Messages API. This code
converts Claude 2 Text Completions request bodies, parses whole and streamed Messages responses (re-attaching a
prefill), builds image content blocks, and prices a month of tokens on each model.

No request reaches Bedrock. Request and response shapes are checked against Anthropic's Python SDK 0.20.0
(`AnthropicBedrock`) and botocore 1.34.64; response contents are synthetic.

## What is here

| Path | What it does |
| --- | --- |
| `claude_migrate/legacy.py` | Splits a `\n\nHuman:` / `\n\nAssistant:` prompt into system, messages and prefill; converts the request body. |
| `claude_migrate/response.py` | Reads a Messages response or stream events into one result; `Result.legacy()` returns the old shape. |
| `claude_migrate/client.py` | `invoke` and `stream` on Bedrock Runtime with adaptive retries. |
| `claude_migrate/content.py` | Text and base64 image content blocks. |
| `claude_migrate/cost.py` | On-demand prices per 1,000 tokens, US East (N. Virginia), March 2024. |
| `tools/demo.py` | Three conversions and a monthly cost comparison. |
| `tools/api_check.py` | What the installed botocore and Anthropic SDK offer. |
| `tests/` | 16 tests, including byte-for-byte comparison with the SDK's request bodies and an AWS event stream decoded by both botocore and the SDK. |

## What was verified

GitHub Actions ([run](https://github.com/nithinmohantk/blog-samples-working-repo/actions/runs/44386686277)), Python 3.12.16, boto3/botocore 1.34.64, anthropic 0.20.0, httpx 0.27.0, pytest 8.1.1 (`--exclude-newer 2024-03-15`).
All 16 tests pass. Cost part of the demo output:

```text
== One month: 50,000,000 input and 10,000,000 output tokens, on-demand, US East (N. Virginia)
  Claude Instant 1.2   $     64.00
  Claude 2.0 / 2.1     $    640.00
  Claude 3 Sonnet      $    300.00
  Claude 3 Haiku       $     25.00
```
