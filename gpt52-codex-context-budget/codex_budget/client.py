"""A session of questions about one repository, sent through the Responses API so that the repository part of
the prompt is identical, byte for byte, from one request to the next and can be served from the prompt cache.

Works against api.openai.com and against Azure OpenAI in Microsoft Foundry through its v1 endpoint: the only
difference is the base_url and what is passed as the key.
"""
from __future__ import annotations

import base64
import hashlib
import mimetypes
import pathlib
from dataclasses import dataclass

from openai import OpenAI

from .budget import Prices, room_for_output

INSTRUCTIONS = (
    "You are reviewing the repository given below. Answer from the files shown. "
    "Name the file and line for every finding, and say so when the files do not contain the answer."
)


class DoesNotFit(ValueError):
    """Raised before any request is sent when the prompt leaves too little of the context window for an answer."""


@dataclass(frozen=True)
class Answer:
    text: str
    input_tokens: int
    cached_tokens: int
    output_tokens: int
    reasoning_tokens: int
    cost: float


class RepositorySession:
    def __init__(self, client: OpenAI, model: str, prices: Prices, encoder, files: dict[str, str],
                 reasoning_effort: str = "medium", max_output_tokens: int = 16_000):
        self._client, self._model, self._prices, self._encoder = client, model, prices, encoder
        self._effort, self._max_output = reasoning_effort, max_output_tokens
        # Files in path order with a fixed header each: the same repository always renders to the same text.
        self._repository = "\n".join(f"### FILE {path}\n{files[path]}" for path in sorted(files))
        self.prefix_tokens = len(encoder.encode(INSTRUCTIONS)) + len(encoder.encode(self._repository))
        # One key per repository snapshot keeps requests that share this prefix on the same cache.
        self._cache_key = "repo-" + hashlib.sha256(self._repository.encode("utf-8")).hexdigest()[:24]

    def ask(self, question: str, image: pathlib.Path | None = None) -> Answer:
        left = room_for_output(self._prices, self.prefix_tokens, len(self._encoder.encode(question)))
        if left < self._max_output:
            raise DoesNotFit(f"{self.prefix_tokens:,} tokens of repository leave {left:,} for the answer; {self._max_output:,} are needed.")

        # Order matters. The repository comes first and never changes; the question and any image come last.
        last: list[dict] = [{"type": "input_text", "text": question}]
        if image is not None:
            kind = mimetypes.guess_type(image.name)[0] or "image/png"
            encoded = base64.b64encode(image.read_bytes()).decode("ascii")
            last.append({"type": "input_image", "image_url": f"data:{kind};base64,{encoded}"})

        response = self._client.responses.create(
            model=self._model,
            instructions=INSTRUCTIONS,
            input=[
                {"role": "user", "content": [{"type": "input_text", "text": self._repository}]},
                {"role": "user", "content": last},
            ],
            reasoning={"effort": self._effort},
            max_output_tokens=self._max_output,
            prompt_cache_key=self._cache_key,
            store=False,   # do not keep the repository in stored responses
        )
        usage = response.usage
        cached = usage.input_tokens_details.cached_tokens
        return Answer(
            text=response.output_text,
            input_tokens=usage.input_tokens,
            cached_tokens=cached,
            output_tokens=usage.output_tokens,
            reasoning_tokens=usage.output_tokens_details.reasoning_tokens,
            cost=self._prices.cost(usage.input_tokens, cached, usage.output_tokens),
        )


def openai_client(api_key: str) -> OpenAI:
    return OpenAI(api_key=api_key, max_retries=4, timeout=600)


def foundry_client(resource: str, api_key_or_token_provider) -> OpenAI:
    """Azure OpenAI in Microsoft Foundry, v1 endpoint. Pass a key, or a token provider from azure.identity
    (get_bearer_token_provider(DefaultAzureCredential(), "https://ai.azure.com/.default")) to use Entra ID.
    The model argument of the session is then the name of your deployment."""
    return OpenAI(base_url=f"https://{resource}.openai.azure.com/openai/v1/", api_key=api_key_or_token_provider, max_retries=4, timeout=600)
