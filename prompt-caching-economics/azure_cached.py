"""azure_cached.py - automatic prompt caching on Azure OpenAI. Nothing to switch on."""
import os

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI

from cache_stats import CacheStats

client = AzureOpenAI(
    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    api_version=os.environ["AZURE_OPENAI_API_VERSION"],
    azure_ad_token_provider=get_bearer_token_provider(
        DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
    ),
)
DEPLOYMENT = os.environ["AZURE_OPENAI_DEPLOYMENT"]


def ask(static_instructions: str, question: str) -> tuple[str, CacheStats]:
    """
    Caching applies on its own once the prompt reaches 1,024 tokens and its first
    1,024 tokens match an earlier request. Keep the static part first.
    """
    response = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=[
            {"role": "system", "content": static_instructions},
            {"role": "user", "content": question},
        ],
        max_completion_tokens=800,
    )

    usage = response.usage
    details = usage.prompt_tokens_details
    cached = (details.cached_tokens or 0) if details else 0
    stats = CacheStats(
        uncached_input_tokens=usage.prompt_tokens - cached,    # prompt_tokens includes cached tokens here
        cache_read_tokens=cached,
        cache_write_tokens=0,
        output_tokens=usage.completion_tokens,
    )
    return response.choices[0].message.content or "", stats
