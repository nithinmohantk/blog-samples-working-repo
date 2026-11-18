# bedrock-healthcare-genai-pipeline

Sample for the dataa.dev article *Taking a GenAI Assistant to Production on Amazon Bedrock: Knowledge Base, Fine-Tuning and Release Gates for Irish Healthcare* (20 June 2026).

The pipeline promotes a candidate assistant configuration (model, prompt, Knowledge Base corpus, Guardrail version) only after it has passed four gates:

| Gate | Module | Blocks when |
| :--- | :--- | :--- |
| Dataset | `pipeline/dataset_gate.py` | a training record is malformed, has no allowed provenance, or contains an Irish identifier (IHI, PPSN) |
| Corpus | `pipeline/kb_metadata.py` | a source document is from an unlisted publisher, contains an identifier, or is past its review date |
| Evaluation | `pipeline/eval_gate.py` | an answer leaks an identifier, a refusal is missed, or recall, citation precision or fact coverage falls below a floor or regresses |
| Sign-off | `pipeline/state_machine.asl.json` | a named clinical safety officer has not approved the report within seven days |

`pipeline/bedrock_clients.py` wraps the Bedrock calls and refuses a customisation job outside the approved training Region, or for a file whose hash differs from its gate certificate. `pipeline/asl_lint.py` checks the state machine's structure and that production cannot be reached without passing the gates.

## Run

```
uv venv -p 3.13 .venv
uv pip install --python .venv --exclude-newer 2026-06-19 boto3 pytest python-stdnum
.venv/bin/python -m pytest
.venv/bin/python -m tools.show_gate candidate_regressed
```

## What was verified

- 30 tests pass on Python 3.13 with boto3 and botocore 1.43.34, pytest 9.1.1 and python-stdnum 2.2, resolved as of 19 June 2026.
- Bedrock requests (`CreateModelCustomizationJob`, `RetrieveAndGenerate`, `CreateGuardrail`) are checked with botocore's Stubber, which validates parameters against the service model. One test confirms the Stubber rejects a misspelt key.
- The PPSN check agrees with python-stdnum on 5,000 random numbers and on the vectors in its documentation. The GS1 check digit matches GS1 UK's worked example.
- The state machine's status values were compared with the botocore service model.

## What was not verified

- Nothing ran against AWS. No customisation job, Knowledge Base, Guardrail or state machine was created; model ids and ARNs are placeholders.
- The state machine was not deployed or run in Step Functions Local.
- The answers in `data/answers/` are hand-written to exercise the gate. They are not model output.

## Data

All data is synthetic. The corpus files are hand-written stand-ins, not extracts of HIQA or HSE publications. The identifier values in the tests are constructed to pass or fail a check digit and do not belong to anyone. **This pattern is not clinically validated** and is not a medical device.

Identifier formats come from the HSE National Policy for Individual Health Identifier (IHI) Data Standards (18-digit GS1 GSRN, or a 10-digit display form) and the HSE page on collecting PPS numbers (seven digits and one or two letters).
