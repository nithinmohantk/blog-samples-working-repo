import random

from stdnum.ie import pps

from pipeline.identifiers import Kind, gs1_check_digit_ok, ppsn_check_ok, scan


def test_gs1_check_digit_matches_gs1_worked_example():
    # GS1 UK worked example: 501234567000C gives C = 3.
    assert gs1_check_digit_ok("5012345670003")
    assert not gs1_check_digit_ok("5012345670004")


def test_constructed_18_digit_identifier_is_found_and_checked():
    findings = scan("Summarise the record for 000000000000000017.")
    assert [f.kind for f in findings] == [Kind.IHI_GSRN]
    assert scan("ref 000000000000000018")[0].kind is Kind.IHI_GSRN_UNCHECKED


def test_spaced_identifier_is_found():
    assert scan("IHI 000 000 000 000 000 017 on file")[0].kind is Kind.IHI_GSRN


def test_ten_digit_form_is_found():
    assert scan("display id 0000000017 shown")[0].kind is Kind.IHI_SHORT


def test_ppsn_vectors_from_python_stdnum_docs():
    for value, valid in [("6433435F", True), ("6433435E", False), ("6433435FW", True),
                         ("6433435OA", True), ("6433435IH", True), ("6433435VH", False)]:
        assert ppsn_check_ok(value) is valid, value


def test_ppsn_check_agrees_with_python_stdnum_on_random_numbers():
    rng = random.Random(20260620)
    letters = "ABCDEFGHIJKLMNOPQRSTUVW"
    for _ in range(5000):
        value = f"{rng.randrange(10**7):07d}{rng.choice(letters)}{rng.choice(['', 'A', 'H', 'W'])}"
        assert ppsn_check_ok(value) == pps.is_valid(value), value


def test_ppsn_found_in_text_and_masked():
    text = "PPSN 1234567T supplied"
    finding = scan(text)[0]
    assert finding.kind is Kind.PPSN
    assert finding.masked(text) == "PPSN:******7T"


def test_ordinary_clinical_text_has_no_findings():
    assert scan("Record what was shared, with whom, when and on what basis [DOC-IM-01].") == []
    assert scan("Version 2024, review due 2027-06-30, 6 results") == []
