# inference-cost-per-token

Companion code for the dataa.dev article *Inferentia2, Trainium or NVIDIA GPUs for LLM Inference: Work Out the Cost per Token* (10 April 2026).

Chip comparisons are usually argued from list prices and vendor benchmarks. This sample works from your own measurements instead:

| File | What it does |
| :--- | :--- |
| `bench.py` | Load generator for any OpenAI-compatible streaming `/v1/completions` endpoint (vLLM on GPU, vLLM with the Neuron plugin on Inferentia2 or Trainium). Reports time to first token, inter-token latency and output tokens per second at each concurrency level, and picks the fastest level that meets your latency targets. |
| `costmodel.py` | Turns instance price, replicas per instance, measured tokens per second and utilisation into cost per million output tokens, sizes a fleet for a peak, and ranks candidates by monthly cost. |
| `example.py` | A worked comparison. Its throughput figures are placeholders, not benchmarks. |

## Use

```bash
pip install httpx==0.28.1
# 1. Serve the model on each candidate with the same model, precision and max length.
# 2. Measure with production-like prompts:
python bench.py --url http://HOST:8000 --model MODEL --prompt-file prompts.txt \
    --concurrency 1 4 8 16 32 --requests 64 --ttft-p95 2.0 --itl-p95 0.1
# 3. Put the reported tokens_per_second into costmodel.Candidate and compare.
python example.py
```

Run the same prompts, output length and latency targets on every candidate, or the comparison is meaningless.

## Tests

```bash
pip install httpx==0.28.1 pytest==9.0.2
python -m pytest -q
```

13 tests: the cost model, and `bench.py` against a local fake streaming server (including failures and multi-token chunks). Tested with Python 3.13.

## Notes

- Inferentia2 serving: Neuron SDK 2.29 (9 April 2026) dropped NxD Inference support for Inf2 and Trn1. Pin Neuron 2.28 for Inf2, or target Trn2 and later.
- Prices change. Check the EC2 and SageMaker pricing pages for your Region and purchase option.
