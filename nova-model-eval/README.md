# nova-model-eval

Companion code for the dataa.dev article *Amazon Nova After 15 Months: Which Model for Which Job, and How to Check* (17 March 2026).

Published benchmarks rarely match your prompts. `evaluate.py` runs your own labelled examples through several Amazon Bedrock models with the Converse API and reports accuracy, p50 and p95 latency, token usage and cost per thousand cases, so the choice between Nova Micro, Nova Lite, Nova 2 Lite or any other model rests on your data.

## Use

```bash
pip install boto3==1.42.55
# cases.jsonl: one {"input": "...", "expected": "LABEL"} per line
python evaluate.py --cases cases.jsonl \
  --system "Classify the query as BILLING, TECHNICAL, SALES or OTHER. Reply with one word." \
  --model us.amazon.nova-micro-v1:0 \
  --model us.amazon.nova-lite-v1:0 \
  --model global.amazon.nova-2-lite-v1:0
# add --reasoning low|medium|high to turn on Nova 2 extended thinking
```

Fill in `PRICES` from the Amazon Bedrock pricing page for your Region, inference profile and service tier before trusting the cost column. Your account needs `bedrock:InvokeModel` on the models and inference profiles you test.

## What it does

- Same system prompt, temperature 0 and token limit for every model.
- Ignores reasoning blocks when scoring; counts reasoning tokens as output, as Bedrock bills them.
- Retries throttling with exponential backoff; counts other errors separately from wrong answers.
- Keeps every mistake so you can read what the model got wrong.

## Tests

```bash
pip install boto3==1.42.55 pytest==9.0.2
python -m pytest -q
```

5 tests using botocore's Stubber, which validates each request against the Bedrock Runtime API model in boto3 1.42.55. Nothing is called on AWS.
