# azure-openai-client

Companion code for the dataa.dev article *Azure OpenAI from Python in November 2024: Keyless Auth, Deployments, Structured Outputs and Failure Handling* (17 November 2024).

`aoai.py`:

- `make_client()` builds an `AzureOpenAI` client that authenticates with Microsoft Entra ID through `azure-identity` (`DefaultAzureCredential`: managed identity in Azure, your developer login locally). No API key is read. It pins the GA API version `2024-10-21` and sets a timeout and retries.
- `extract_invoice()` uses structured outputs with a Pydantic model, so the answer is validated against a JSON schema. Refusals, content-filter blocks (on the prompt or the completion) and truncated answers come back as distinct outcomes.

## Use

```bash
pip install openai==1.54.4 azure-identity==1.19.0
export AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com
python -c "import aoai; print(aoai.extract_invoice(aoai.make_client(), '<deployment>', open('invoice.txt').read()))"
```

The identity needs the **Cognitive Services OpenAI User** role on the Azure OpenAI resource. Structured outputs need a model version that supports them, such as `gpt-4o` 2024-08-06.

## Tests

```bash
pip install openai==1.54.4 azure-identity==1.19.0 pydantic==2.9.2 httpx==0.27.2 pytest==8.3.3
python -m pytest -q
```

6 tests against a mocked endpoint (httpx `MockTransport`): the deployment URL path, `api-version`, the bearer token from the token provider and no `api-key` header, a strict JSON schema in the request and a parsed `Invoice` back; refusal; completion content filter; prompt content filter (HTTP 400 `content_filter`); other 400s raised; truncated answers. No Azure calls. Tested with Python 3.12.
