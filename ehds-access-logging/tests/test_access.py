import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data"))

from ehds_access import categories as C  # noqa: E402
from ehds_access.audit import Requester, access_event, origin_of  # noqa: E402
from ehds_access.gateway import AccessGateway  # noqa: E402
from ehds_access.report import keep_until, may_delete, render, rows  # noqa: E402
from ehds_access.restrict import Restriction, searchset, visible  # noqa: E402
from seed import RESOURCES  # noqa: E402

BY_ID = {r["id"]: r for r in RESOURCES}
HOSPITAL = Requester("Practitioner/dr-hosp-a", "Dr Hospital-A", "Organization/hospital-a", "Hospital A")
GP = Requester("Practitioner/dr-gp-b", "Dr GP-B", "Organization/gp-b", "GP Practice B")
P = "Patient/ehds-p1"
NO_LABS = Restriction(P, frozenset({C.TEST_RESULTS}), frozenset({"Organization/gp-b"}))


def test_every_seed_resource_maps_to_the_expected_category():
    got = {r["id"]: C.category_of(r) for r in RESOURCES if r["resourceType"] not in ("Patient", "Organization", "Practitioner")}
    assert got == {"summary-1": C.PATIENT_SUMMARY, "rx-1": C.EPRESCRIPTION, "dispense-1": C.EDISPENSATION,
                   "hba1c-1": C.TEST_RESULTS, "creat-1": C.TEST_RESULTS, "bp-1": None,
                   "lab-report-1": C.TEST_RESULTS, "xray-report-1": C.IMAGING, "discharge-1": C.DISCHARGE_REPORT}


def test_article_72_dates_split_the_categories_into_two_groups():
    assert {c for c, y in C.APPLIES_AFTER_YEARS.items() if y == 4} == {C.PATIENT_SUMMARY, C.EPRESCRIPTION, C.EDISPENSATION}
    assert set(C.APPLIES_AFTER_YEARS) == set(C.PRIORITY)


def test_audit_event_carries_annex_ii_3_4_a_to_e():
    when = datetime(2024, 3, 22, 10, 15, tzinfo=timezone.utc)
    e = access_event(HOSPITAL, P, [BY_ID["hba1c-1"], BY_ID["discharge-1"]], interaction="search-type", when=when)
    who = {a["who"]["reference"] for a in e["agent"]}
    assert who == {"Organization/hospital-a", "Practitioner/dr-hosp-a"}           # (a) provider, (b) individual
    details = [{d["type"]: d["valueString"] for d in ent["detail"]} for ent in e["entity"] if "detail" in ent]
    assert [d["ehds-category"] for d in details] == [C.TEST_RESULTS, C.DISCHARGE_REPORT]   # (c)
    assert e["recorded"] == "2024-03-22T10:15:00.000+00:00"                          # (d)
    assert [d["ehds-origin"] for d in details] == ["Organization/lab-d", "Organization/hospital-a"]  # (e)
    assert e["purposeOfEvent"][0]["coding"][0]["code"] == "TREAT"


def test_origin_reads_dispense_actor_and_falls_back_to_meta_source():
    assert origin_of(BY_ID["dispense-1"]) == "Organization/pharmacy-c"
    assert origin_of({"resourceType": "ImagingStudy", "meta": {"source": "urn:pacs-1"}}) == "urn:pacs-1"


def test_restriction_hides_the_category_and_the_count_does_not_give_it_away():
    observations = [BY_ID["hba1c-1"], BY_ID["creat-1"], BY_ID["bp-1"]]
    shown = visible(observations, NO_LABS, HOSPITAL.organization)
    assert [r["id"] for r in shown] == ["bp-1"]
    bundle = searchset(shown)
    assert bundle["total"] == 1 and "restrict" not in str(bundle).lower()


def test_allowed_provider_and_emergency_see_everything():
    observations = [BY_ID["hba1c-1"], BY_ID["creat-1"], BY_ID["bp-1"]]
    assert len(visible(observations, NO_LABS, GP.organization)) == 3
    assert len(visible(observations, NO_LABS, HOSPITAL.organization, emergency=True)) == 3


class FakeFhir:
    def __init__(self, found, fail_create=False):
        self.found, self.created, self.fail_create = found, [], fail_create

    def search_all(self, rtype, params):
        return list(self.found), len(self.found)

    def create(self, resource):
        if self.fail_create:
            raise OSError("audit store down")
        self.created.append(resource)
        return resource


def test_gateway_logs_only_what_it_shows():
    fhir = FakeFhir([BY_ID["hba1c-1"], BY_ID["creat-1"], BY_ID["bp-1"]])
    result = AccessGateway(fhir, {P: NO_LABS}).search(HOSPITAL, P, "Observation")
    logged = [ent["what"]["reference"] for ent in fhir.created[0]["entity"][1:]]
    assert result["total"] == 1 and logged == ["Observation/bp-1"]


def test_gateway_returns_nothing_if_the_access_cannot_be_logged():
    with pytest.raises(OSError):
        AccessGateway(FakeFhir([BY_ID["bp-1"]], fail_create=True)).search(GP, P, "Observation")


def test_emergency_access_is_marked_in_the_patient_report():
    t = datetime(2024, 3, 22, 3, 40, tzinfo=timezone.utc)
    events = [access_event(GP, P, [BY_ID["summary-1"]], interaction="search-type", when=t.replace(hour=1)),
              access_event(HOSPITAL, P, [BY_ID["hba1c-1"]], interaction="search-type", emergency=True, when=t)]
    report = rows(events)
    assert report[0].emergency and report[0].categories == (C.TEST_RESULTS,)
    assert rows(events, show_individual=False)[0].individual is None
    assert "EMERGENCY ACCESS" in render(report).splitlines()[1]


@pytest.mark.parametrize("recorded, now, expected", [
    ("2024-03-22T10:00:00+00:00", datetime(2027, 3, 22, 9, 59, tzinfo=timezone.utc), False),
    ("2024-03-22T10:00:00+00:00", datetime(2027, 3, 22, 10, 0, tzinfo=timezone.utc), True),
    ("2024-02-29T08:00:00+00:00", datetime(2027, 2, 28, 23, 0, tzinfo=timezone.utc), False),
    ("2024-02-29T08:00:00+00:00", datetime(2027, 3, 1, 8, 0, tzinfo=timezone.utc), True),
])
def test_three_year_minimum(recorded, now, expected):
    assert may_delete({"recorded": recorded}, now) is expected


def test_leap_day_access_is_kept_until_1_march():
    assert keep_until(datetime(2024, 2, 29, tzinfo=timezone.utc)) == datetime(2027, 3, 1, tzinfo=timezone.utc)
