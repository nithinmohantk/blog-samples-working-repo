# prompt-caching-economics

Sample code for the dataa.dev article "Prompt Caching Economics on Amazon Bedrock and Azure OpenAI".

- `caching_economics.py` - the cost model: hit probability, relative cost and break-even points.
- `cache_stats.py` - one shape for cache usage from either provider.
- `bedrock_cached.py` - explicit caching with a Bedrock Converse `cachePoint`.
- `azure_cached.py` - automatic caching on Azure OpenAI, reading `cached_tokens`.
- `test_model.py`, `test_caching.py` - tests. No cloud account is needed.

```
pip install -r requirements.txt
python test_model.py
python test_caching.py
```

The multipliers in `caching_economics.py` are those published in June 2026. Replace them with current rates before using the model for a decision. Nothing here made a live model call.
