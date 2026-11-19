# cowork-folder-check

Sample code for the dataa.dev article *Anthropic Claude Cowork: Building General-Purpose AI Agents for Enterprise Knowledge Work* (24 January 2026).

Cowork works on the folders you grant it. Anthropic's guidance for the research preview is to avoid granting access to local files with sensitive information. `folder_check.py` reads a folder before you grant it and reports:

- **HIGH**: key and credential files (`.env`, `*.pem`, `id_rsa`, `credentials` and similar), private key blocks, AWS access key IDs, GitHub, Slack and Anthropic tokens, and symbolic links that point outside the folder.
- **MEDIUM**: personal data that passes a checksum: payment card numbers (Luhn), IBANs (mod 97) and Irish PPS numbers (mod 23 check character).
- **LOW**: email addresses, files over 100 MB, and binary files it could not scan (PDF, Office files, images).

Matched values are masked. The script only reads files and makes no network calls. It is a pre-flight check, not a data loss prevention system: it does not open PDFs or Office documents, and pattern checks miss data in other formats.

## Run it

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python folder_check.py ~/Work/q1-board-pack           # exit code 1 if anything HIGH
python folder_check.py ~/Work/q1-board-pack --json
pytest -q
```

No third-party packages are needed to run the script; `pytest` is only for the tests.

## What has been verified

- 14 pytest tests pass on Python 3.13 with `pytest==9.0.2`, covering the checksum functions, credential and key detection, masking, symbolic links that escape the folder, and binary files.
- It has not been run against Cowork itself; it checks a folder before you grant it.
