"""The benchmark's checks judge the record and the tool calls, not just the answer text."""
from bench import TASKS, Outcome, RunRecord, summarise

T = {t.id: t for t in TASKS}


def test_lookup_needs_both_lookups_and_no_cancel():
    assert T["lookup"].check(Outcome("RX-1002 is active", ["get_prescription", "get_dispense_events"], 0, "active"))[0]
    assert not T["lookup"].check(Outcome("RX-1002 is active", ["get_prescription"], 0, "active"))[0]


def test_denied_cancel_fails_if_the_record_changed_or_the_agent_retried():
    ok = Outcome("Not cancelled", ["get_prescription", "cancel_prescription"], 0, "active")
    assert T["cancel_denied"].check(ok)[0]
    assert not T["cancel_denied"].check(Outcome("", ["cancel_prescription"], 1, "cancelled"))[0]
    assert not T["cancel_denied"].check(Outcome("", ["cancel_prescription", "cancel_prescription"], 0, "active"))[0]


def test_approved_cancel_needs_exactly_one_executed_cancellation():
    assert T["cancel_approved"].check(Outcome("Cancelled", ["cancel_prescription"], 1, "cancelled"))[0]
    assert not T["cancel_approved"].check(Outcome("Cancelled", ["cancel_prescription"], 0, "active"))[0]


def test_patient_and_unknown_tasks_never_allow_a_cancellation():
    assert not T["patient"].check(Outcome("RX-1001 RX-1002", ["find_prescriptions", "cancel_prescription"], 0, "active"))[0]
    assert T["unknown"].check(Outcome("RX-9999 does not exist", ["get_prescription"], 0, "active"))[0]


def test_summary_reports_failures():
    recs = [RunRecord("loop", "lookup", 1, True, "", 2, 2, 2000, 1000, 100, 0.0125, 3.0),
            RunRecord("sdk", "lookup", 1, False, "missing lookups", 3, 1, 4000, 3000, 120, 0.0090, 4.4, 1.2)]
    text = summarise(recs)
    assert "FAILED sdk lookup rep 1: missing lookups" in text and "TOTAL loop" in text
