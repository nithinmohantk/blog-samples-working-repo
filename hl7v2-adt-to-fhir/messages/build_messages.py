"""Writes the synthetic HL7 v2 messages in this folder.

    python build_messages.py

Fields are given by their HL7 number, so nobody has to count pipes. Every person, number, address and
telephone number here is invented. The files use line feeds so they diff well; a real feed uses carriage returns,
and the reader accepts both.
"""
import pathlib

HERE = pathlib.Path(__file__).parent


def segment(name: str, fields: dict[int, str]) -> str:
    first = 2 if name == "MSH" else 1          # MSH-1 is the separator itself
    values = [fields.get(n, "") for n in range(first, max(fields) + 1)]
    return "|".join([name, *values])


def msh(trigger: str, control: str, when: str, version: str = "2.5.1", structure: str | None = None) -> str:
    kind = f"ADT^{trigger}" + (f"^{structure}" if structure else "")
    return segment("MSH", {2: "^~\\&", 3: "ADTSYS", 4: "GENHOSP", 5: "FHIRGW", 6: "REGION", 7: when, 9: kind, 10: control, 11: "P", 12: version})


AOIFE = {
    3: "700001^^^GENHOSP^MR~PT-55-0193^^^REGION^PI",
    5: "O'Brien^Aoife^Mary^^Ms^^L~Byrne^Aoife^^^^^M",
    7: "19850312", 8: "F",
    11: "Flat 2, Smith \\T\\ Sons Building^14 Example Street^Exampletown^^EX1 2MP^IE^H",
    13: "^PRN^PH^^^^^^^^^+353 20 910 0101~^NET^Internet^aoife.obrien@example.org",
    14: "^WPN^PH^^^^^^^^^+353 20 910 0102",
    16: "M",
}
AOIFE_MOVED = AOIFE | {
    11: "9 Sample Road^^Exampletown^^EX4 7QT^IE^H",
    13: "^PRN^CP^^^^^^^^^+353 20 910 0199~^NET^Internet^aoife.obrien@example.org",
}
SPOUSE = segment("NK1", {1: "1", 2: "O'Brien^Cian", 3: "SPO^Spouse^HL70063", 5: "^PRN^CP^^^^^^^^^+353 20 910 0103", 7: "C^Emergency Contact^HL70131"})
PENICILLIN = segment("AL1", {1: "1", 2: "DA", 3: "91936005^Allergy to penicillin^SCT", 4: "SV", 5: "Rash", 6: "20190601"})
PEANUT = segment("AL1", {1: "2", 2: "FA", 3: "91935009^Allergy to peanut^SCT", 4: "MO"})
LATEX = segment("AL1", {1: "3", 2: "EA", 3: "LATEX^Latex^99LOCAL", 4: "MI"})


def visit(number: str, patient_class: str, where: str, admitted: str, discharged: str = "") -> str:
    return segment("PV1", {1: "1", 2: patient_class, 3: where, 7: "D1001^Murphy^Niamh^^^Dr^^^GENHOSP", 19: f"{number}^^^GENHOSP^VN", 44: admitted, 45: discharged})


MESSAGES = {
    "01-a01-admit.hl7": [
        msh("A01", "MSG00001", "20260310081500+0000", structure="ADT_A01"), segment("EVN", {1: "A01", 2: "20260310081500+0000"}),
        segment("PID", {1: "1"} | AOIFE), SPOUSE, visit("V9001", "I", "W4^R12^B^GENHOSP", "20260310080000+0000"), PENICILLIN, PEANUT,
    ],
    "02-a08-update.hl7": [
        msh("A08", "MSG00002", "20260310113000+0000", structure="ADT_A01"), segment("EVN", {1: "A08", 2: "20260310113000+0000"}),
        segment("PID", {1: "1"} | AOIFE_MOVED), SPOUSE, visit("V9001", "I", "W4^R12^B^GENHOSP", "20260310080000+0000"), PENICILLIN, PEANUT, LATEX,
    ],
    "03-a03-discharge.hl7": [
        msh("A03", "MSG00003", "20260312140000+0000", structure="ADT_A03"), segment("EVN", {1: "A03", 2: "20260312140000+0000", 6: "20260312133000+0000"}),
        segment("PID", {1: "1"} | AOIFE_MOVED), visit("V9001", "I", "W4^R12^B^GENHOSP", "20260310080000+0000", "20260312133000+0000"),
    ],
    # The same person registered a second time in the emergency department, under a new number.
    "04-a01-second-registration.hl7": [
        msh("A01", "MSG00004", "20260313090000+0000", structure="ADT_A01"), segment("EVN", {1: "A01", 2: "20260313090000+0000"}),
        segment("PID", {1: "1", 3: "700002^^^GENHOSP^MR", 5: "OBrien^Aoife^^^^^L", 7: "19850312", 8: "F"}),
        visit("V9002", "E", "ED^^3^GENHOSP", "20260313085500+0000"),
    ],
    "05-a11-cancel-admit.hl7": [
        msh("A11", "MSG00005", "20260313093000+0000", structure="ADT_A09"), segment("EVN", {1: "A11", 2: "20260313093000+0000"}),
        segment("PID", {1: "1", 3: "700002^^^GENHOSP^MR", 5: "OBrien^Aoife^^^^^L", 7: "19850312", 8: "F"}),
        visit("V9002", "E", "ED^^3^GENHOSP", "20260313085500+0000"),
    ],
    "06-a40-merge.hl7": [
        msh("A40", "MSG00006", "20260313100000+0000", structure="ADT_A39"), segment("EVN", {1: "A40", 2: "20260313100000+0000"}),
        segment("PID", {1: "1"} | AOIFE_MOVED), segment("MRG", {1: "700002^^^GENHOSP^MR"}),
    ],
    # A system that has not heard about the merge still writes to the retired number.
    "07-a08-to-retired-record.hl7": [
        msh("A08", "MSG00007", "20260313110000+0000", structure="ADT_A01"), segment("EVN", {1: "A08", 2: "20260313110000+0000"}),
        segment("PID", {1: "1", 3: "700002^^^GENHOSP^MR", 5: "OBrien^Aoife^^^^^L", 7: "19850312", 8: "F", 13: "^PRN^PH^^^^^^^^^+353 20 910 0177"}),
    ],
    # An older v2.3.1 sender: no message structure, times without an offset, a month-precision birth date, a sex
    # code outside table 0001, a marital code that means something else in FHIR, an escaped field separator,
    # an explicit null, and a Z-segment.
    "08-a04-older-sender.hl7": [
        msh("A04", "MSG00008", "202603131015", version="2.3.1"), segment("EVN", {1: "A04", 2: "202603131015"}),
        segment("PID", {1: "1", 3: "700003^^^GENHOSP^MR", 5: "Walsh^Tom^^^^^L", 7: "198011", 8: "X", 11: "3 Test Lane \\F\\ Rear Annex^^Exampletown^^EX2 9ZZ^IE^H", 13: '""', 16: "A^Separated"}),
        segment("NK1", {1: "1", 3: "MTH^Mother"}),
        visit("V9003", "O", "OPD^^^GENHOSP", "202603131000"), segment("AL1", {1: "1", 2: "MA", 3: "^House dust"}), segment("ZPD", {1: "1", 2: "LOCALFLAG"}),
    ],
    "09-a02-transfer.hl7": [
        msh("A02", "MSG00009", "20260313120000+0000", structure="ADT_A02"), segment("EVN", {1: "A02", 2: "20260313120000+0000"}),
        segment("PID", {1: "1"} | AOIFE_MOVED), visit("V9001", "I", "W5^R01^A^GENHOSP", "20260310080000+0000"),
    ],
    "10-a01-no-record-number.hl7": [
        msh("A01", "MSG00010", "20260313130000+0000", structure="ADT_A01"), segment("EVN", {1: "A01", 2: "20260313130000+0000"}),
        segment("PID", {1: "1", 3: "PT-77-0001^^^REGION^PI", 5: "Nolan^Sean^^^^^L", 7: "19700101", 8: "M"}), visit("V9004", "I", "W1^R01^A^GENHOSP", "20260313125000+0000"),
    ],
    # After the merge: a later update to the surviving record.
    "11-a08-after-merge.hl7": [
        msh("A08", "MSG00011", "20260314090000+0000", structure="ADT_A01"), segment("EVN", {1: "A08", 2: "20260314090000+0000"}),
        segment("PID", {1: "1"} | AOIFE_MOVED | {14: "^WPN^PH^^^^^^^^^+353 20 910 0155"}), SPOUSE, PENICILLIN, PEANUT, LATEX,
    ],
    # A sparse update: only what changed. The address is withdrawn with an explicit null; everything not sent stays.
    "12-a08-sparse-update.hl7": [
        msh("A08", "MSG00016", "20260314130000+0000", structure="ADT_A01"), segment("EVN", {1: "A08", 2: "20260314130000+0000"}),
        segment("PID", {1: "1", 3: "700003^^^GENHOSP^MR", 5: "Walsh^Tom^^^^^L", 11: '""', 13: "^PRN^PH^^^^^^^^^+353 20 910 0188"}),
    ],
}

for name, lines in MESSAGES.items():
    (HERE / name).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
print(f"wrote {len(MESSAGES)} messages")
