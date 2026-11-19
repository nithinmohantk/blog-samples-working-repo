"""Worked example. The throughput figures are PLACEHOLDERS, not benchmarks:
replace them with bench.py results for your model, prompts and latency target.
Prices are us-east-1 Linux on-demand list prices; check the EC2 pricing page.
"""
from costmodel import Candidate, compare

candidates = [
    Candidate("inf2.48xlarge (12 Inferentia2)", hourly_usd=12.98, replicas_per_instance=2, tokens_per_second=900),
    Candidate("g6e.12xlarge (4x L40S)", hourly_usd=10.49, replicas_per_instance=1, tokens_per_second=1400),
    Candidate("p5.48xlarge (8x H100)", hourly_usd=55.04, replicas_per_instance=4, tokens_per_second=2500),
]

# Peak of 3,000 output tokens/s, averaging 30% of that over the month
peak = 3000
monthly_tokens = peak * 0.3 * 3600 * 730

for row in compare(candidates, peak_tokens_per_second=peak, monthly_tokens=monthly_tokens):
    print(f"{row['name']:<32} instances={row['instances']:>2} "
          f"monthly=${row['monthly_usd']:>10,.0f} utilisation={row['utilisation']:.0%} "
          f"per-million=${row['usd_per_million']:.2f}")
