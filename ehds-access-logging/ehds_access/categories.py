"""Article 5(1): the priority categories of personal electronic health data.

The provisional agreement lists six. The text does not say how a FHIR resource maps to them; that comes
with the European electronic health record exchange format in implementing acts. This mapping is a
working assumption, kept in one place so it can change when those acts arrive.
"""
from __future__ import annotations

PATIENT_SUMMARY = "patient-summary"           # Art. 5(1)(a)
EPRESCRIPTION = "eprescription"               # Art. 5(1)(b)
EDISPENSATION = "edispensation"               # Art. 5(1)(c)
IMAGING = "imaging"                           # Art. 5(1)(d) imaging studies and related reports
TEST_RESULTS = "test-results"                 # Art. 5(1)(e) laboratory and other diagnostic results and reports
DISCHARGE_REPORT = "discharge-report"         # Art. 5(1)(f)

PRIORITY = (PATIENT_SUMMARY, EPRESCRIPTION, EDISPENSATION, IMAGING, TEST_RESULTS, DISCHARGE_REPORT)

# Article 72: categories (a) to (c) apply four years after entry into force, (d) to (f) six years after.
APPLIES_AFTER_YEARS = {PATIENT_SUMMARY: 4, EPRESCRIPTION: 4, EDISPENSATION: 4,
                       IMAGING: 6, TEST_RESULTS: 6, DISCHARGE_REPORT: 6}

LOINC = "http://loinc.org"
V2_0074 = "http://terminology.hl7.org/CodeSystem/v2-0074"          # DiagnosticReport.category
OBS_CATEGORY = "http://terminology.hl7.org/CodeSystem/observation-category"
DOC_TYPES = {"60591-5": PATIENT_SUMMARY, "18842-5": DISCHARGE_REPORT}  # Patient summary, Discharge summary
RADIOLOGY = {"RAD", "CT", "MR", "RX", "US", "NMR", "OUS"}


def _codes(concepts: list[dict] | dict | None, system: str) -> set[str]:
    if isinstance(concepts, dict):
        concepts = [concepts]
    return {c.get("code") for cc in concepts or [] for c in cc.get("coding", []) if c.get("system") == system}


def category_of(resource: dict) -> str | None:
    """The Article 5 category of one FHIR R4 resource, or None if it is outside the priority categories."""
    rtype = resource.get("resourceType")
    if rtype == "MedicationRequest":
        return EPRESCRIPTION
    if rtype == "MedicationDispense":
        return EDISPENSATION
    if rtype == "ImagingStudy":
        return IMAGING
    if rtype in ("Composition", "DocumentReference"):
        for code in _codes(resource.get("type"), LOINC):
            if code in DOC_TYPES:
                return DOC_TYPES[code]
        return None
    if rtype == "DiagnosticReport":
        cats = _codes(resource.get("category"), V2_0074)
        return IMAGING if cats & RADIOLOGY else TEST_RESULTS
    if rtype == "Observation":
        cats = _codes(resource.get("category"), OBS_CATEGORY)
        if "imaging" in cats:
            return IMAGING
        return TEST_RESULTS if cats & {"laboratory", "procedure"} else None
    return None
