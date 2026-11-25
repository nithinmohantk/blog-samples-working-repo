"""Model configuration for every example.

The sample runs against Azure OpenAI with Microsoft Entra ID (no API keys) or
against OpenAI with OPENAI_API_KEY. Deployment and model names are
configuration, never literals in the examples.

  RAG_PROVIDER=azure   AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_CHAT_DEPLOYMENT,
                       AZURE_OPENAI_EMBED_DEPLOYMENT, AZURE_OPENAI_API_VERSION,
                       AZURE_OPENAI_CHAT_MODEL (the model behind the deployment,
                       used for context-window and token limits)
  RAG_PROVIDER=openai  OPENAI_API_KEY, OPENAI_CHAT_MODEL, OPENAI_EMBED_MODEL
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from llama_index.core import Settings

DEFAULT_API_VERSION = "2024-10-21"


@dataclass(frozen=True)
class ModelConfig:
    provider: str
    chat_model: str  # deployment name on Azure, model name on OpenAI
    embed_model: str
    model_name: str = "gpt-4o"
    endpoint: str | None = None
    api_version: str = DEFAULT_API_VERSION


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is not set")
    return value


def load_config() -> ModelConfig:
    provider = os.environ.get("RAG_PROVIDER", "azure").strip().lower()
    if provider == "azure":
        return ModelConfig(
            provider="azure",
            endpoint=_require("AZURE_OPENAI_ENDPOINT"),
            chat_model=_require("AZURE_OPENAI_CHAT_DEPLOYMENT"),
            embed_model=_require("AZURE_OPENAI_EMBED_DEPLOYMENT"),
            model_name=os.environ.get("AZURE_OPENAI_CHAT_MODEL", "gpt-4o"),
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", DEFAULT_API_VERSION),
        )
    if provider == "openai":
        _require("OPENAI_API_KEY")
        return ModelConfig(
            provider="openai",
            chat_model=os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o"),
            embed_model=os.environ.get("OPENAI_EMBED_MODEL", "text-embedding-3-small"),
        )
    raise RuntimeError(f"RAG_PROVIDER must be 'azure' or 'openai', not {provider!r}")


def configure(config: ModelConfig | None = None, *, timeout: float = 60.0, max_retries: int = 3) -> ModelConfig:
    """Set the global LLM and embedding model, with timeouts and retries on both."""
    config = config or load_config()
    if config.provider == "azure":
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider
        from llama_index.embeddings.azure_openai import AzureOpenAIEmbedding
        from llama_index.llms.azure_openai import AzureOpenAI

        token_provider = get_bearer_token_provider(
            DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
        )
        Settings.llm = AzureOpenAI(
            model=config.model_name,
            engine=config.chat_model,
            azure_endpoint=config.endpoint,
            api_version=config.api_version,
            azure_ad_token_provider=token_provider,
            use_azure_ad=True,
            temperature=0.0,
            timeout=timeout,
            max_retries=max_retries,
        )
        Settings.embed_model = AzureOpenAIEmbedding(
            deployment_name=config.embed_model,
            azure_endpoint=config.endpoint,
            api_version=config.api_version,
            azure_ad_token_provider=token_provider,
            use_azure_ad=True,
            max_retries=max_retries,
            embed_batch_size=64,
        )
    else:
        from llama_index.embeddings.openai import OpenAIEmbedding
        from llama_index.llms.openai import OpenAI

        Settings.llm = OpenAI(model=config.chat_model, temperature=0.0, timeout=timeout, max_retries=max_retries)
        Settings.embed_model = OpenAIEmbedding(model=config.embed_model, max_retries=max_retries, embed_batch_size=64)
    return config
