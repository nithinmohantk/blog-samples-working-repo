"""
fhir_statements.py
Turns FHIR R4 resources into short clinical statements that are safe to embed and to show a model.
Each statement keeps its provenance, so every sentence in an answer can be traced to a resource.
"""
import base64
from dataclasses import dataclass, field

# Records that must never reach a prompt as if they were facts about the patient.
EXCLUDED_STATUS = {"entered-in-error", "cancelled", "unknown"}
EXCLUDED_VERIFICATION = {"entered-in-error", "refuted"}


@dataclass(frozen=True)
class Statement:
    patient_id: str
    resource: str            # "Observation/obs-2": the citation
    kind: str                # resource type
    date: str                # clinically relevant date, ISO 8601, may be ""
    text: str
    codes: tuple[str, ...] = ()
    pinned: bool = False     # always sent to the model, never left to similarity search


@dataclass
class RenderReport:
    statements: list[Statement] = field(default_factory=list)
    excluded: list[tuple[str, str]] = field(default_factory=list)     # (resource, reason)
    unsupported: list[str] = field(default_factory=list)              # resource types with no renderer


def _codes(concept: dict | None) -> tuple[str, ...]:
    return tuple(f"{c.get('system', '')}|{c.get('code', '')}" for c in (concept or {}).get("coding", []))


def _label(concept: dict | None) -> str:
    concept = concept or {}
    if concept.get("text"):
        return concept["text"]
    return next((c["display"] for c in concept.get("coding", []) if c.get("display")), "unspecified")


def _first_code(concept: dict | None) -> str:
    return next((c.get("code", "") for c in (concept or {}).get("coding", [])), "")


def _patient_id(resource: dict) -> str:
    ref = (resource.get("subject") or resource.get("patient") or {}).get("reference", "")
    return ref.split("/")[-1]


def _condition(r: dict):
    verification = _first_code(r.get("verificationStatus"))
    if verification in EXCLUDED_VERIFICATION:
        return None, f"verificationStatus={verification}"
    clinical = _first_code(r.get("clinicalStatus")) or "status not recorded"
    date = r.get("onsetDateTime") or r.get("recordedDate", "")
    return (date, f"Condition ({clinical}): {_label(r.get('code'))}. Onset {date or 'not recorded'}.",
            _codes(r.get("code")), False), None


def _observation(r: dict):
    if r.get("status") in EXCLUDED_STATUS:
        return None, f"status={r.get('status')}"
    date = r.get("effectiveDateTime", "")
    q = r.get("valueQuantity")
    if q:
        value = f"{q.get('value')} {q.get('unit') or q.get('code') or '(unit not recorded)'}"
    else:
        value = r.get("valueString") or _label(r.get("valueCodeableConcept"))
    flag = _label(r["interpretation"][0]) if r.get("interpretation") else ""
    text = f"Observation on {date or 'unknown date'}: {_label(r.get('code'))} = {value}"
    return (date, text + (f" ({flag})." if flag else "."), _codes(r.get("code")), False), None


def _medication_request(r: dict):
    status = r.get("status", "unknown")
    if status in EXCLUDED_STATUS:
        return None, f"status={status}"
    date = r.get("authoredOn", "")
    dose = (r.get("dosageInstruction") or [{}])[0].get("text", "dose not recorded")
    text = f"Medication ({status}): {_label(r.get('medicationCodeableConcept'))}, {dose}. Prescribed {date or 'date not recorded'}."
    return (date, text, _codes(r.get("medicationCodeableConcept")), status == "active"), None


def _allergy(r: dict):
    verification = _first_code(r.get("verificationStatus"))
    if verification in EXCLUDED_VERIFICATION:
        return None, f"verificationStatus={verification}"
    reactions = ", ".join(_label(m) for rx in r.get("reaction", []) for m in rx.get("manifestation", [])) or "not recorded"
    text = (f"Allergy or intolerance ({r.get('criticality', 'criticality not recorded')}): "
            f"{_label(r.get('code'))}. Reaction: {reactions}.")
    return (r.get("recordedDate", ""), text, _codes(r.get("code")), True), None


RENDERERS = {"Condition": _condition, "Observation": _observation,
             "MedicationRequest": _medication_request, "AllergyIntolerance": _allergy}


def _document_chunks(r: dict, patient_id: str, max_chars: int = 600) -> list[Statement]:
    """Free-text notes are the one place where semantic search earns its keep."""
    if r.get("status") in EXCLUDED_STATUS or r.get("docStatus") == "entered-in-error":
        return []
    out = []
    for content in r.get("content", []):
        att = content.get("attachment", {})
        if not att.get("contentType", "").startswith("text/plain") or "data" not in att:
            continue
        note = base64.b64decode(att["data"]).decode("utf-8")
        paragraphs, buf = [p.strip() for p in note.split("\n\n") if p.strip()], ""
        for para in paragraphs + [""]:
            if buf and (not para or len(buf) + len(para) > max_chars):
                out.append(Statement(patient_id, f"DocumentReference/{r['id']}", "DocumentReference",
                                     r.get("date", ""), f"Note ({_label(r.get('type'))}, {r.get('date', '')[:10]}): {buf}"))
                buf = ""
            buf = f"{buf}\n{para}".strip()
    return out


def render_bundle(bundle: dict) -> RenderReport:
    report = RenderReport()
    for entry in bundle.get("entry", []):
        r = entry["resource"]
        kind, ref = r["resourceType"], f"{r['resourceType']}/{r.get('id', '?')}"
        if kind == "Patient":
            continue                                   # demographics are not embedded
        patient_id = _patient_id(r)
        if not patient_id:
            report.excluded.append((ref, "no patient reference"))
            continue
        if kind == "DocumentReference":
            chunks = _document_chunks(r, patient_id)
            report.statements.extend(chunks) if chunks else report.excluded.append((ref, "no usable text"))
            continue
        renderer = RENDERERS.get(kind)
        if renderer is None:
            report.unsupported.append(kind)            # reported, never silently dropped
            continue
        rendered, reason = renderer(r)
        if rendered is None:
            report.excluded.append((ref, reason))
            continue
        date, text, codes, pinned = rendered
        report.statements.append(Statement(patient_id, ref, kind, date, text, codes, pinned))
    return report
