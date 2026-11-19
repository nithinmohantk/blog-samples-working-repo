import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import folder_check as fc  # noqa: E402


def write(root: Path, rel: str, text: str | bytes) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text if isinstance(text, bytes) else text.encode())
    return path


def codes(report):
    return {(f.severity, f.code) for f in report.findings}


@pytest.mark.parametrize("value,ok", [("1234567T", True), ("1234567FA", True), ("1234567A", False), ("1234567TA", False)])
def test_ppsn_check_character(value, ok):
    assert fc.ppsn_ok(value) is ok


@pytest.mark.parametrize("value,ok", [("GB82 WEST 1234 5698 7654 32", True), ("IE29AIBK93115212345678", True),
                                      ("GB82 WEST 1234 5698 7654 33", False)])
def test_iban_checksum(value, ok):
    assert fc.iban_ok(value) is ok


def test_luhn():
    assert fc.luhn_ok("4111111111111111")
    assert not fc.luhn_ok("4111111111111112")


def test_clean_folder_has_no_findings(tmp_path):
    write(tmp_path, "q1/notes.md", "# Q1 review\nRevenue grew in March.\n")
    write(tmp_path, "q1/figures.csv", "month,revenue\nJan,100\nFeb,120\n")
    report = fc.scan(tmp_path)
    assert report.findings == []
    assert report.files_scanned == 2
    assert fc.main([str(tmp_path)]) == 0


def test_credentials_are_high(tmp_path):
    write(tmp_path, ".env", "DB_PASSWORD=hunter2\n")
    write(tmp_path, "deploy/notes.txt", "key AKIAIOSFODNN7EXAMPLE for the pipeline\n")
    write(tmp_path, "keys/server.pem", "-----BEGIN RSA PRIVATE KEY-----\nMIIB\n-----END RSA PRIVATE KEY-----\n")
    found = codes(fc.scan(tmp_path))
    assert ("HIGH", "KEY_OR_CREDENTIAL_FILE") in found
    assert ("HIGH", "AWS_ACCESS_KEY_ID") in found
    assert ("HIGH", "PRIVATE_KEY_BLOCK") in found
    assert fc.main([str(tmp_path)]) == 1


def test_personal_data_needs_a_valid_checksum(tmp_path):
    write(tmp_path, "patients.csv",
          "name,ppsn,iban,card,email\n"
          "A,1234567T,IE29AIBK93115212345678,4111 1111 1111 1111,a@example.ie\n")
    write(tmp_path, "order-ids.txt", "Order 1234567A shipped. Ref 4111111111111112.\n")
    report = fc.scan(tmp_path)
    by_path = {(f.path, f.code) for f in report.findings}
    assert {("patients.csv", "IE_PPSN"), ("patients.csv", "IBAN"), ("patients.csv", "PAYMENT_CARD"),
            ("patients.csv", "EMAIL_ADDRESSES")} <= by_path
    assert not any(p == "order-ids.txt" for p, _ in by_path)
    assert report.count("HIGH") == 0


def test_values_are_masked(tmp_path, capsys):
    write(tmp_path, "cards.txt", "4111 1111 1111 1111\n")
    fc.main([str(tmp_path), "--json"])
    out = capsys.readouterr().out
    assert "4111111111111111" not in out and "4111 1111 1111 1111" not in out
    assert json.loads(out)["findings"][0]["detail"].endswith("4111**********11")


def test_link_outside_folder_is_high(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    write(outside, "secret.txt", "x")
    shared = tmp_path / "shared"
    shared.mkdir()
    os.symlink(outside, shared / "escape")
    os.symlink(outside / "secret.txt", shared / "file-link")
    write(shared, "inside.txt", "ok")
    os.symlink(shared / "inside.txt", shared / "inside-link")
    found = [(f.code, f.path) for f in fc.scan(shared).findings]
    assert ("LINK_OUTSIDE_FOLDER", "escape") in found
    assert ("LINK_OUTSIDE_FOLDER", "file-link") in found
    assert not any(p == "inside-link" for _, p in found)


def test_binary_files_are_reported_not_scanned(tmp_path):
    write(tmp_path, "scan.pdf", b"%PDF-1.7\x00\x01binary")
    assert ("LOW", "NOT_SCANNED") in codes(fc.scan(tmp_path))
