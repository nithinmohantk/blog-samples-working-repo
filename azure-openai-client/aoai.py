"""Calling Azure OpenAI from Python with keyless auth and structured outputs.

- `make_client`: an `AzureOpenAI` client that authenticates with Microsoft
  Entra ID (managed identity in Azure, your developer login locally) through
  `azure-identity`, pins the GA API version, and sets timeouts and retries.
- `extract_invoice`: structured outputs. The response is validated against a
  Pydantic model; refusals, content-filter blocks and truncated answers are
  reported as distinct outcomes instead of exceptions deep in parsing.

Environment:
    AZURE_OPENAI_ENDPOINT    https://<resource>.openai.azure.com
    AZURE_OPENAI_DEPLOYMENT  the deployment name (not the model name)
    AZURE_OPENAI_API_VERSION optional, defaults to the GA version 2024-10-21
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

from openai import AzureOpenAI, BadRequestError, ContentFilterFinishReasonError, LengthFinishReasonError
from pydantic import BaseModel, Field

GA_API_VERSION = "2024-10-21"
SCOPE = "https://cognitiveservices.azure.com/.default"


def make_client(endpoint: str | None = None, api_version: str | None = None,
                token_provider: Callable[[], str] | None = None, **kwargs) -> AzureOpenAI:
    """Build a client that uses Entra ID tokens; no API key is read or stored."""
    endpoint = endpoint or os.environ["AZURE_OPENAI_ENDPOINT"]
    if token_provider is None:
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider
        token_provider = get_bearer_token_provider(DefaultAzureCredential(), SCOPE)
    return AzureOpenAI(
        azure_endpoint=endpoint,
        api_version=api_version or os.environ.get("AZURE_OPENAI_API_VERSION", GA_API_VERSION),
        azure_ad_token_provider=token_provider,
        timeout=kwargs.pop("timeout", 60.0),
        max_retries=kwargs.pop("max_retries", 3),      # 429 and 5xx, honouring retry-after
        **kwargs,
    )


class LineItem(BaseModel):
    description: str
    quantity: float
    unit_price: float


class Invoice(BaseModel):
    supplier: str
    invoice_number: str
    currency: str = Field(description="ISO 4217 code, for example EUR")
    total: float
    lines: list[LineItem]


@dataclass
class Outcome:
    status: str                    # "ok", "refused", "filtered", "truncated"
    invoice: Invoice | None = None
    detail: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0


SYSTEM = ("Extract the invoice fields from the user's text. Use only values present in the text. "
          "If a value is missing, use an empty string or 0.")


def extract_invoice(client: AzureOpenAI, deployment: str, text: str) -> Outcome:
    try:
        resp = client.beta.chat.completions.parse(
            model=deployment,                          # Azure: the deployment name
            messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}],
            response_format=Invoice,
            temperature=0,
            max_tokens=800,
        )
    except LengthFinishReasonError:
        # The SDK will not parse a cut-off JSON answer
        return Outcome("truncated", detail="raise max_tokens or shorten the input")
    except ContentFilterFinishReasonError:
        return Outcome("filtered", detail="completion blocked by content filtering")
    except BadRequestError as exc:
        body = exc.body if isinstance(exc.body, dict) else {}
        if body.get("code") == "content_filter":
            return Outcome("filtered", detail="prompt blocked by content filtering")
        raise
    choice = resp.choices[0]
    usage = (resp.usage.prompt_tokens, resp.usage.completion_tokens) if resp.usage else (0, 0)
    if choice.message.refusal:
        return Outcome("refused", detail=choice.message.refusal, prompt_tokens=usage[0], completion_tokens=usage[1])
    return Outcome("ok", invoice=choice.message.parsed, prompt_tokens=usage[0], completion_tokens=usage[1])
