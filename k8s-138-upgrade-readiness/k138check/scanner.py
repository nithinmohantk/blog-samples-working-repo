"""Walk files, run the checks, print a report and return an exit code.

Exit codes: 0 no finding at or above the threshold, 1 at least one such
finding, 2 the scan itself could not run (bad arguments, nothing to scan).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .checks import DOCUMENT_CHECKS, REMOVED_KUBECTL_ENV_VARS, check_env_vars
from .findings import Finding, Severity

log = logging.getLogger("k138check")

MAX_FILE_BYTES = 2 * 1024 * 1024
SKIPPED_DIRECTORIES = {".git", "node_modules", ".terraform", ".venv", "venv", "__pycache__", "vendor"}
YAML_SUFFIXES = {".yaml", ".yml", ".json"}
YAML_FILENAMES = {"kuberc"}

try:  # The C loader is several times faster on large manifest trees.
    _SafeLoader: Any = yaml.CSafeLoader
except AttributeError:  # pragma: no cover - depends on how PyYAML was built
    _SafeLoader = yaml.SafeLoader


@dataclass(slots=True)
class ScanResult:
    findings: list[Finding] = field(default_factory=list)
    files_scanned: int = 0
    documents_scanned: int = 0
    skipped: list[tuple[str, str]] = field(default_factory=list)

    def worst(self) -> Severity | None:
        return max((f.severity for f in self.findings), default=None)


def iter_files(roots: Iterable[Path]) -> Iterator[Path]:
    """Yield regular files under the roots in a stable order, without following links."""
    for root in roots:
        if root.is_file():
            yield root
            continue
        for directory, subdirectories, filenames in os.walk(root, followlinks=False):
            subdirectories[:] = sorted(d for d in subdirectories if d not in SKIPPED_DIRECTORIES)
            for filename in sorted(filenames):
                candidate = Path(directory, filename)
                if candidate.is_file() and not candidate.is_symlink():
                    yield candidate


def _is_yaml_candidate(path: Path) -> bool:
    return path.suffix.lower() in YAML_SUFFIXES or path.name in YAML_FILENAMES


def _expand_lists(document: Any) -> Iterator[Mapping[str, Any]]:
    """Yield objects, opening `kind: List` wrappers such as `kubectl get -o yaml` output."""
    if not isinstance(document, Mapping):
        return
    items = document.get("items")
    if str(document.get("kind", "")).endswith("List") and isinstance(items, list):
        for item in items:
            yield from _expand_lists(item)
    else:
        yield document


def scan_file(path: Path, result: ScanResult) -> None:
    display = path.as_posix()
    try:
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            result.skipped.append((display, f"larger than {MAX_FILE_BYTES} bytes"))
            return
        raw = path.read_bytes()
    except OSError as exc:
        result.skipped.append((display, f"unreadable: {exc.strerror or exc}"))
        return

    if b"\x00" in raw[:8192]:
        return  # binary file; not counted, not reported
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        result.skipped.append((display, "not UTF-8 text"))
        return

    result.files_scanned += 1
    if any(variable in text for variable in REMOVED_KUBECTL_ENV_VARS):
        result.findings.extend(check_env_vars(display, text))

    if not _is_yaml_candidate(path):
        return
    try:
        documents = list(yaml.load_all(text, Loader=_SafeLoader))
    except yaml.YAMLError as exc:
        # Helm and other templates are not valid YAML until rendered.
        problem = getattr(exc, "problem", None) or "invalid YAML"
        result.skipped.append((display, f"not parsed ({problem}); render templates first"))
        return

    for document in documents:
        for obj in _expand_lists(document):
            result.documents_scanned += 1
            for check in DOCUMENT_CHECKS:
                result.findings.extend(check(display, obj))


def scan(roots: Sequence[Path]) -> ScanResult:
    result = ScanResult()
    for path in iter_files(roots):
        scan_file(path, result)
    result.findings.sort(key=lambda f: (-f.severity, f.check, f.path, f.subject))
    return result


def render_text(result: ScanResult) -> str:
    lines: list[str] = []
    for finding in result.findings:
        lines += [
            f"[{finding.severity.name}] {finding.check}  {finding.path}  ({finding.subject})",
            f"    {finding.message}",
            f"    Action: {finding.action}",
            f"    Reference: {finding.reference}",
            "",
        ]
    counts = {s: sum(1 for f in result.findings if f.severity is s) for s in Severity}
    lines.append(
        f"{result.files_scanned} files, {result.documents_scanned} objects scanned: "
        f"{counts[Severity.ACTION]} action, {counts[Severity.WARN]} warn, {counts[Severity.INFO]} info, "
        f"{len(result.skipped)} skipped"
    )
    for path, reason in result.skipped:
        lines.append(f"  skipped {path}: {reason}")
    return "\n".join(lines)


def render_json(result: ScanResult) -> str:
    payload = {
        "filesScanned": result.files_scanned,
        "objectsScanned": result.documents_scanned,
        "findings": [f.to_dict() for f in result.findings],
        "skipped": [{"path": p, "reason": r} for p, r in result.skipped],
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="k138check",
        description="Static upgrade-readiness checks for Kubernetes v1.38.",
    )
    parser.add_argument("paths", nargs="+", type=Path, help="files or directories to scan")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument(
        "--fail-on",
        default="action",
        help="lowest severity that makes the exit code 1: info, warn or action (default: action)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="log progress to stderr")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    try:
        threshold = Severity.parse(args.fail_on)
    except ValueError as exc:
        parser.error(str(exc))  # exits with status 2

    missing = [str(p) for p in args.paths if not p.exists()]
    if missing:
        log.error("path does not exist: %s", ", ".join(missing))
        return 2

    result = scan(args.paths)
    log.debug("scanned %d files, %d objects", result.files_scanned, result.documents_scanned)
    if result.files_scanned == 0:
        log.error("no readable text files under the given paths")
        return 2

    print(render_json(result) if args.format == "json" else render_text(result))
    worst = result.worst()
    return 1 if worst is not None and worst >= threshold else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
