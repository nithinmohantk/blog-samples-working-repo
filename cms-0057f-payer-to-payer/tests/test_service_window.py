import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "client"))
from service_window import decide, five_years_before, service_date  # noqa: E402

REQUEST = date(2024, 1, 19)


def eob(start, end=None):
    return {"resourceType": "ExplanationOfBenefit", "id": "x", "billablePeriod": {"start": start, "end": end or start}}


def test_window_boundary_is_inclusive():
    assert five_years_before(REQUEST) == date(2019, 1, 19)
    assert decide(eob("2019-01-19"), REQUEST).keep
    assert not decide(eob("2019-01-18"), REQUEST).keep


def test_leap_day_request():
    assert five_years_before(date(2024, 2, 29)) == date(2019, 2, 28)


def test_end_of_period_is_the_date_of_service():
    # A stay that started before the window and ended inside it is in scope.
    assert decide(eob("2019-01-10", "2019-01-25"), REQUEST).keep


def test_datetime_values_are_truncated_to_dates():
    obs = {"resourceType": "Observation", "id": "o", "effectiveDateTime": "2023-12-02T08:15:00+00:00"}
    assert service_date(obs) == date(2023, 12, 2)


def test_no_date_is_held_not_sent():
    d = decide({"resourceType": "Condition", "id": "c"}, REQUEST)
    assert not d.keep and "held" in d.reason


def test_future_date_is_not_sent():
    assert decide(eob("2024-02-01"), REQUEST).reason == "date of service after the request"


def test_context_resources_always_sent():
    assert decide({"resourceType": "Coverage", "id": "c"}, REQUEST).keep


def test_unknown_type_is_held():
    assert not decide({"resourceType": "DocumentReference", "id": "d", "date": "2023-01-01"}, REQUEST).keep
