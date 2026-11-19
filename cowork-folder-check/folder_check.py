"""Check a folder before granting an AI agent (such as Claude Cowork) access to it.

Anthropic's guidance for the Cowork research preview is to avoid giving the
agent access to local files with sensitive information. This script reads a
folder and reports what should not be in it:

- HIGH: credentials and keys (key files, private key blocks, cloud and SaaS
  tokens) and symbolic links that point outside the folder.
- MEDIUM: personal data that passes a checksum: payment card numbers (Luhn),
  IBANs (ISO 13616 mod 97) and Irish PPS numbers (mod 23 check character).
- LOW: email addresses, very large files, and binary files that were skipped.

Matched values are masked in the output. The script only reads files; it
never changes, moves or uploads anything.
Exit code: 0 when there are no HIGH findings, 1 when there are, 2 on usage errors.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

MAX_SCAN_BYTES = 5 * 1024 * 1024
LARGE_FILE_BYTES = 100 * 1024 * 1024
TEXT_SUFFIXES = {".txt", ".md", ".csv", ".tsv", ".json", ".yaml", ".yml", ".xml", ".html",
                 ".ini", ".cfg", ".conf", ".env", ".properties", ".py", ".js", ".ts", ".sql",
                 ".log", ".sh", ".ps1", ".pem", ".key", ""}
KEY_FILE_NAMES = {".env", "id_rsa", "id_ecdsa", "id_ed25519", "credentials", ".npmrc", ".pypirc",
                  ".netrc", "kubeconfig", ".git-credentials"}
KEY_FILE_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".kdbx", ".ovpn"}

SECRET_PATTERNS = {
    "PRIVATE_KEY_BLOCK": re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"),
    "AWS_ACCESS_KEY_ID": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "GITHUB_TOKEN": re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}\b|\bgithub_pat_[A-Za-z0-9_]{60,}\b"),
    "SLACK_TOKEN": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    "ANTHROPIC_API_KEY": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"),
}
CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b")
PPSN = re.compile(r"\b\d{7}[A-W][A-IW]?\b")
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


@dataclass
class Finding:
    severity: str  # HIGH, MEDIUM or LOW
    code: str
    path: str
    detail: str = ""


@dataclass
class Report:
    folder: str
    files_scanned: int = 0
    bytes_total: int = 0
    findings: list[Finding] = field(default_factory=list)

    def count(self, severity: str) -> int:
        return sum(1 for f in self.findings if f.severity == severity)


def mask(value: str) -> str:
    compact = re.sub(r"[ -]", "", value)
    return compact[:4] + "*" * max(len(compact) - 6, 0) + compact[-2:]


def luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def iban_ok(value: str) -> bool:
    s = value.replace(" ", "")
    if not 15 <= len(s) <= 34:
        return False
    rearranged = s[4:] + s[:4]
    number = "".join(str(int(c, 36)) for c in rearranged)
    return int(number) % 97 == 1


def ppsn_ok(value: str) -> bool:
    """Irish Personal Public Service Number: 7 digits, a check letter and an optional second letter."""
    digits, check, extra = value[:7], value[7], value[8:]
    total = sum(int(d) * w for d, w in zip(digits, range(8, 1, -1)))
    if extra:
        total += 9 * (0 if extra == "W" else ord(extra) - 64)
    remainder = total % 23
    return check == ("W" if remainder == 0 else chr(64 + remainder))


def _is_text(path: Path, head: bytes) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES and b"\x00" not in head


def scan_text(rel: str, text: str) -> list[Finding]:
    out: list[Finding] = []
    for code, pattern in SECRET_PATTERNS.items():
        m = pattern.search(text)
        if m:
            out.append(Finding("HIGH", code, rel, mask(m.group())))
    cards = [m.group() for m in CARD.finditer(text)
             if 13 <= len(re.sub(r"[ -]", "", m.group())) <= 19 and luhn_ok(re.sub(r"[ -]", "", m.group()))]
    if cards:
        out.append(Finding("MEDIUM", "PAYMENT_CARD", rel, f"{len(cards)} found, e.g. {mask(cards[0])}"))
    ibans = [m.group() for m in IBAN.finditer(text) if iban_ok(m.group())]
    if ibans:
        out.append(Finding("MEDIUM", "IBAN", rel, f"{len(ibans)} found, e.g. {mask(ibans[0])}"))
    ppsns = [m.group() for m in PPSN.finditer(text) if ppsn_ok(m.group())]
    if ppsns:
        out.append(Finding("MEDIUM", "IE_PPSN", rel, f"{len(ppsns)} found, e.g. {mask(ppsns[0])}"))
    emails = EMAIL.findall(text)
    if emails:
        out.append(Finding("LOW", "EMAIL_ADDRESSES", rel, f"{len(emails)} found"))
    return out


def scan(folder: Path) -> Report:
    root = folder.resolve()
    report = Report(folder=str(root))
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        for name in list(dirnames):
            link = current / name
            if link.is_symlink():
                dirnames.remove(name)
                _check_link(root, link, report)
        for name in filenames:
            path = current / name
            rel = str(path.relative_to(root))
            if path.is_symlink():
                _check_link(root, path, report)
                continue
            size = path.stat().st_size
            report.files_scanned += 1
            report.bytes_total += size
            if name.lower() in KEY_FILE_NAMES or path.suffix.lower() in KEY_FILE_SUFFIXES:
                report.findings.append(Finding("HIGH", "KEY_OR_CREDENTIAL_FILE", rel))
            if size > LARGE_FILE_BYTES:
                report.findings.append(Finding("LOW", "LARGE_FILE", rel, f"{size // (1024 * 1024)} MB"))
            with path.open("rb") as fh:
                head = fh.read(MAX_SCAN_BYTES)
            if not _is_text(path, head[:8192]):
                if path.suffix.lower() not in KEY_FILE_SUFFIXES:
                    report.findings.append(Finding("LOW", "NOT_SCANNED", rel, "binary or unsupported format"))
                continue
            report.findings.extend(scan_text(rel, head.decode("utf-8", errors="replace")))
    return report


def _check_link(root: Path, link: Path, report: Report) -> None:
    target = link.resolve()
    if target != root and root not in target.parents:
        report.findings.append(Finding("HIGH", "LINK_OUTSIDE_FOLDER", str(link.relative_to(root)), str(target)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if not args.folder.is_dir():
        parser.error(f"{args.folder} is not a directory")
    report = scan(args.folder)
    if args.json:
        print(json.dumps(asdict(report), indent=2))
    else:
        print(f"Folder: {report.folder}")
        print(f"Files:  {report.files_scanned} ({report.bytes_total / 1024 / 1024:.1f} MB)")
        print(f"HIGH {report.count('HIGH')}  MEDIUM {report.count('MEDIUM')}  LOW {report.count('LOW')}")
        for f in sorted(report.findings, key=lambda f: ("HIGH", "MEDIUM", "LOW").index(f.severity)):
            print(f"  {f.severity:<6} {f.code}: {f.path}" + (f" ({f.detail})" if f.detail else ""))
    return 1 if report.count("HIGH") else 0


if __name__ == "__main__":
    sys.exit(main())
