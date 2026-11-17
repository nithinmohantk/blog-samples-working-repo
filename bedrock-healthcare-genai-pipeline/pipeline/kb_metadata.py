"""Builds the Knowledge Base corpus: one metadata sidecar per source document.

The corpus is what the assistant knows. Each document carries its publisher,
version and review date, so a superseded standard can be filtered out at query
time and every answer can name the edition it came from.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .identifiers import scan

PUBLISHERS = {"HIQA", "HSE", "DoH"}


@dataclass(frozen=True)
class SourceDocument:
    doc_id: str
    file: str
    title: str
    publisher: str
    version: str
    published: date
    review_due: date
    superseded_by: str | None = None

    def status(self, as_of: date) -> str:
        if self.superseded_by:
            return "superseded"
        return "current" if self.review_due >= as_of else "review-overdue"


def load_manifest(path: Path) -> list[SourceDocument]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    return [
        SourceDocument(
            doc_id=r["doc_id"], file=r["file"], title=r["title"], publisher=r["publisher"],
            version=r["version"], published=date.fromisoformat(r["published"]),
            review_due=date.fromisoformat(r["review_due"]), superseded_by=r.get("superseded_by"),
        )
        for r in rows
    ]


def sidecar(doc: SourceDocument, as_of: date) -> dict:
    """Content of `<file>.metadata.json` for an S3 data source."""
    return {
        "metadataAttributes": {
            "doc_id": doc.doc_id,
            "title": doc.title,
            "publisher": doc.publisher,
            "version": doc.version,
            "published": doc.published.isoformat(),
            "published_year": doc.published.year,
            "status": doc.status(as_of),
        }
    }


def check_corpus(docs: list[SourceDocument], corpus_dir: Path, as_of: date) -> list[str]:
    problems: list[str] = []
    seen: set[str] = set()
    for doc in docs:
        if doc.doc_id in seen:
            problems.append(f"{doc.doc_id}: duplicate doc_id")
        seen.add(doc.doc_id)
        if doc.publisher not in PUBLISHERS:
            problems.append(f"{doc.doc_id}: publisher {doc.publisher} not on the allow list")
        source = corpus_dir / doc.file
        if not source.exists():
            problems.append(f"{doc.doc_id}: {doc.file} missing")
            continue
        text = source.read_text(encoding="utf-8")
        for finding in scan(text):
            problems.append(f"{doc.doc_id}: identifier in source text ({finding.masked(text)})")
        if doc.status(as_of) == "review-overdue":
            problems.append(f"{doc.doc_id}: review date {doc.review_due} has passed")
    return problems


def write_sidecars(docs: list[SourceDocument], corpus_dir: Path, as_of: date) -> list[Path]:
    written = []
    for doc in docs:
        target = corpus_dir / f"{doc.file}.metadata.json"
        target.write_text(json.dumps(sidecar(doc, as_of), indent=2) + "\n", encoding="utf-8")
        written.append(target)
    return written


def current_documents_filter() -> dict:
    """Retrieval filter: current editions from approved publishers only."""
    return {
        "andAll": [
            {"equals": {"key": "status", "value": "current"}},
            {"in": {"key": "publisher", "value": sorted(PUBLISHERS)}},
        ]
    }
