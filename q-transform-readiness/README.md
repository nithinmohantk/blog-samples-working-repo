# q-transform-readiness

Sample code for the dataa.dev article *Legacy to Serverless: Automated Codebase Modernization with Amazon Q Developer* (7 April 2026).

## What is here

- `readiness.py` reads a repository and checks it against the documented prerequisites for an Amazon Q Developer Java transformation: Maven build, Java 8, 11, 17 or 21 source, Maven 3.8 or later, no plugins that package non-Java code, no tests that need a private database, UTF-8 sources. It then recommends one tool:
  - `q-developer-java`: Amazon Q Developer Java upgrade in the IDE (targets Java 17 or 21).
  - `aws-transform-custom`: AWS Transform custom, for Gradle builds or projects Amazon Q cannot take.
  - `aws-transform-dotnet`: AWS Transform for .NET, for .NET Framework projects.
  - `manual`: nothing recognised.
- `dependency-upgrade.yaml` is an example of the dependency upgrade file Amazon Q accepts for a library-only transformation. `readiness.py --deps-file` checks its required fields.
- `strangler/template.yaml` is an AWS SAM template for a strangler-fig facade: an HTTP API that sends `POST /orders` to a Java 21 Lambda function and proxies everything else to the existing application. `CodeUri` points at `order-intake/`, the module you extract; it is not included.

The scanner reads files only. It does not build the project and makes no AWS calls.

## Run it

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python readiness.py /path/to/legacy-repo --deps-file dependency-upgrade.yaml
python readiness.py /path/to/legacy-repo --json   # exit code 1 if there are blockers
pytest -q
cfn-lint strangler/template.yaml
```

## What has been verified

- 14 pytest tests pass on Python 3.13 with `pyyaml==6.0.3` and `pytest==9.0.2`.
- `strangler/template.yaml` passes `cfn-lint` 1.48.1, including the SAM transform.
- The template has not been deployed by these tests. Deploy it with `sam build && sam deploy --guided` once `order-intake/` exists.
