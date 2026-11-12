"""bedrock_cached.py - explicit prompt caching with the Amazon Bedrock Converse API."""
import os

import boto3

from cache_stats import CacheStats

MODEL_ID = os.environ["BEDROCK_MODEL_ID"]      # a model that supports prompt caching
bedrock = boto3.client("bedrock-runtime")


def ask(static_instructions: str, question: str, one_hour: bool = False) -> tuple[str, CacheStats]:
    """
    static_instructions must be byte-for-byte identical between calls and long enough to
    meet the model's minimum (1,024 tokens on some Claude models, 4,096 on others).
    """
    cache_point = {"type": "default"}
    if one_hour:
        cache_point["ttl"] = "1h"              # only on models that offer the 1-hour option

    response = bedrock.converse(
        modelId=MODEL_ID,
        system=[
            {"text": static_instructions},     # everything above the checkpoint is the cached prefix
            {"cachePoint": cache_point},
        ],
        messages=[{"role": "user", "content": [{"text": question}]}],   # dynamic content goes last
        inferenceConfig={"maxTokens": 800},
    )

    usage = response["usage"]
    stats = CacheStats(
        uncached_input_tokens=usage["inputTokens"],            # excludes cached tokens on Bedrock
        cache_read_tokens=usage.get("cacheReadInputTokens", 0),
        cache_write_tokens=usage.get("cacheWriteInputTokens", 0),
        output_tokens=usage["outputTokens"],
    )
    text = "".join(block.get("text", "") for block in response["output"]["message"]["content"])
    return text, stats
