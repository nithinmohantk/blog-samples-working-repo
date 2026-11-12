"""Ask an Azure OpenAI deployment for findings in the shape of the extraction schema.

    python azure_extractor.py request                  print the schema and instructions; no network
    python azure_extractor.py propose <note.txt>       call the deployment and print proposals for review
                                                       needs AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_DEPLOYMENT
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

import clinical_coding as cc

SCHEMA_NAME = "clinical_findings"
ROOT = pathlib.Path(__file__).resolve().parent.parent


def build_request(note_text: str, subset: dict, deployment: str) -> dict:
    """The keyword arguments for chat.completions.create."""
    schema = cc.build_schema(subset)
    problems = cc.lint_schema(schema)
    if problems:
        raise ValueError("the schema does not meet the structured output limits: " + "; ".join(problems))
    return {
        "model": deployment,
        "messages": [{"role": "system", "content": cc.system_prompt(subset)}, {"role": "user", "content": note_text}],
        "response_format": {"type": "json_schema", "json_schema": {"name": SCHEMA_NAME, "strict": True, "schema": schema}},
    }


def propose(note_text: str, subset: dict, endpoint: str, deployment: str) -> list[dict]:
    """Return proposals for a reviewer. Raises ShapeError when the response cannot be used."""
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider
    from openai import APIStatusError, OpenAI

    # Microsoft Entra ID, not an API key: the identity needs the Cognitive Services OpenAI User role.
    token_provider = get_bearer_token_provider(DefaultAzureCredential(), "https://ai.azure.com/.default")
    client = OpenAI(base_url=endpoint.rstrip("/") + "/openai/v1/", api_key=token_provider, timeout=60, max_retries=3)
    try:
        completion = client.chat.completions.create(**build_request(note_text, subset, deployment))
    except APIStatusError as error:
        # Status only. The message can echo request content, and the request is a clinical note.
        raise RuntimeError(f"The model call failed with HTTP status {error.status_code}.") from None
    choice = completion.choices[0]
    # A response cut off by the token limit or a content filter is not a short answer: it is no answer.
    if choice.finish_reason != "stop":
        raise cc.ShapeError(f"the response did not complete: {choice.finish_reason}")
    if choice.message.refusal:
        raise cc.ShapeError("the model refused the request")
    return cc.guard(cc.parse_response(choice.message.content or "", subset), note_text, subset)


def main() -> int:
    subset = cc.load_subset(str(ROOT / "terminology" / "coding-subset.json"))
    if len(sys.argv) == 2 and sys.argv[1] == "request":
        request = build_request("", subset, "")["response_format"]["json_schema"]
        print(json.dumps({**request, "system": cc.system_prompt(subset)}, indent=2))
        return 0
    if len(sys.argv) == 3 and sys.argv[1] == "propose":
        endpoint, deployment = os.environ.get("AZURE_OPENAI_ENDPOINT"), os.environ.get("AZURE_OPENAI_DEPLOYMENT")
        if not endpoint or not deployment:
            print("Set AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_DEPLOYMENT.", file=sys.stderr)
            return 2
        try:
            proposals = propose(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"), subset, endpoint, deployment)
        except (cc.ShapeError, RuntimeError) as error:
            print(f"No proposals: {error}", file=sys.stderr)
            return 1
        print(json.dumps(proposals, indent=2, default=str))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
