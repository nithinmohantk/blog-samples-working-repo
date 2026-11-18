"""
fhir_retrieval.py
Patient-scoped retrieval over rendered FHIR statements, with a structured path for questions
that have an exact answer in coded data and a semantic path for everything else.
"""
import hashlib
import math
import re
from typing import Protocol
from urllib.parse import urlencode

from fhir_statements import Statement

LOINC = "http://loinc.org"
# Questions with one right answer go to coded data. Extend from your own terminology service.
CODED_CONCEPTS = {
    "hba1c": (LOINC, "4548-4"), "glycated haemoglobin": (LOINC, "4548-4"), "a1c": (LOINC, "4548-4"),
    "egfr": (LOINC, "62238-1"), "creatinine": (LOINC, "2160-0"), "potassium": (LOINC, "2823-3"),
}
LATEST = re.compile(r"\b(latest|last|most recent|current)\b", re.I)


class Embedder(Protocol):
    def embed(self, text: str) -> list[float]: ...


class HashingEmbedder:
    """Deterministic stand-in for tests. Production uses a real embedding model behind the same method."""

    def __init__(self, dims: int = 256) -> None:
        self.dims = dims

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dims
        for token in re.findall(r"[a-z0-9]+", text.lower()):
            vec[int(hashlib.sha256(token.encode()).hexdigest(), 16) % self.dims] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class PatientIndex:
    """One partition per patient. The patient id selects the partition; it is never a similarity signal."""

    def __init__(self, embedder: Embedder) -> None:
        self._embedder = embedder
        self._partitions: dict[str, list[tuple[Statement, list[float]]]] = {}

    def add(self, statements: list[Statement]) -> None:
        for s in statements:
            self._partitions.setdefault(s.patient_id, []).append((s, self._embedder.embed(s.text)))

    def statements(self, patient_id: str) -> list[Statement]:
        return [s for s, _ in self._partitions.get(patient_id, [])]

    def search(self, patient_id: str, question: str, k: int = 5) -> list[Statement]:
        q = self._embedder.embed(question)
        scored = [(sum(a * b for a, b in zip(q, v)), s) for s, v in self._partitions.get(patient_id, [])]
        return [s for score, s in sorted(scored, key=lambda t: t[0], reverse=True)[:k] if score > 0]

    def purge(self, patient_id: str) -> int:
        """Erasure: remove every derived record when the source record is erased."""
        return len(self._partitions.pop(patient_id, []))


def coded_concept(question: str) -> tuple[str, str] | None:
    lowered = question.lower()
    return next((code for term, code in CODED_CONCEPTS.items() if term in lowered), None)


def fhir_search_url(base_url: str, patient_id: str, system: str, code: str, count: int = 1) -> str:
    """The same question asked of the FHIR server directly. Works on HealthLake and the Azure FHIR service."""
    query = urlencode({"patient": patient_id, "code": f"{system}|{code}", "_sort": "-date", "_count": count})
    return f"{base_url.rstrip('/')}/Observation?{query}"


def retrieve(index: PatientIndex, patient_id: str, question: str, k: int = 5) -> dict:
    """Returns pinned safety facts, plus either an exact coded answer or semantic matches."""
    everything = index.statements(patient_id)
    pinned = [s for s in everything if s.pinned]
    concept = coded_concept(question)
    if concept and LATEST.search(question):
        token = f"{concept[0]}|{concept[1]}"
        matches = sorted((s for s in everything if token in s.codes), key=lambda s: s.date, reverse=True)
        return {"route": "structured", "pinned": pinned, "evidence": matches[:1]}
    evidence = [s for s in index.search(patient_id, question, k) if not s.pinned]
    return {"route": "semantic", "pinned": pinned, "evidence": evidence}


def build_context(result: dict) -> str:
    def lines(items):
        return "\n".join(f"- {s.text} [{s.resource}]" for s in items) or "- none recorded"
    return ("Answer only from the record extracts below. Cite the bracketed resource for every statement. "
            "If the extracts do not contain the answer, say that the record does not show it.\n\n"
            f"ALWAYS CONSIDER (allergies and active medication):\n{lines(result['pinned'])}\n\n"
            f"EVIDENCE FOR THIS QUESTION:\n{lines(result['evidence'])}")
