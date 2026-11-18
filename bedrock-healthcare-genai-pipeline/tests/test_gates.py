import json
from datetime import date
from pathlib import Path

import pytest

from pipeline import dataset_gate, eval_gate, kb_metadata
from pipeline.asl_lint import lint, lint_file

DATA = Path(__file__).resolve().parents[1] / "data"
ROOT = Path(__file__).resolve().parents[1]
AS_OF = date(2026, 6, 20)


def test_fixture_training_set_passes_and_strips_metadata(tmp_path):
    out = tmp_path / "train.jsonl"
    result = dataset_gate.run_gate(DATA / "training/train_source.jsonl", out, min_records=6)
    assert result.passed, dataset_gate.report(result)
    assert result.provenance == {"synthetic": 4, "author-written": 2}
    first = json.loads(out.read_text().splitlines()[0])
    assert set(first) == {"schemaVersion", "system", "messages"}
    assert result.certificate()["personal_data"] is False


def test_real_minimum_size_is_enforced(tmp_path):
    result = dataset_gate.run_gate(DATA / "training/train_source.jsonl", tmp_path / "t.jsonl")
    assert [p.code for p in result.problems] == ["SIZE"]
    assert not (tmp_path / "t.jsonl").exists()
    with pytest.raises(ValueError):
        result.certificate()


def test_identifier_wrong_roles_and_missing_provenance_are_caught(tmp_path):
    bad = {
        "schemaVersion": "bedrock-conversation-2024",
        "messages": [
            {"role": "user", "content": [{"text": "Patient IHI 000000000000000017, PPSN 1234567T"}]},
            {"role": "user", "content": [{"text": "again"}]},
        ],
        "metadata": {"provenance": "ward-export"},
    }
    source = tmp_path / "bad.jsonl"
    source.write_text(json.dumps(bad) + "\n")
    result = dataset_gate.run_gate(source, tmp_path / "out.jsonl", min_records=1)
    codes = sorted(p.code for p in result.problems)
    assert codes == ["IDENTIFIER", "IDENTIFIER", "PROVENANCE", "ROLES", "ROLES"]
    # The report never prints the identifier itself.
    assert "000000000000000017" not in dataset_gate.report(result)


def test_corpus_check_and_sidecars(tmp_path):
    docs = kb_metadata.load_manifest(DATA / "corpus/manifest.json")
    assert kb_metadata.check_corpus(docs, DATA / "corpus", AS_OF) == []
    statuses = {d.doc_id: d.status(AS_OF) for d in docs}
    assert statuses == {"DOC-IM-01": "current", "DOC-ID-02": "current",
                        "DOC-PIA-03": "current", "DOC-IM-00": "superseded"}
    for doc in docs:
        (tmp_path / doc.file).write_text("x")
    written = kb_metadata.write_sidecars(docs, tmp_path, AS_OF)
    sidecar = json.loads(written[0].read_text())
    assert sidecar["metadataAttributes"]["doc_id"] == "DOC-IM-01"
    assert written[0].name == "im-standards-summary.md.metadata.json"


def test_review_date_passing_blocks_the_corpus():
    docs = kb_metadata.load_manifest(DATA / "corpus/manifest.json")
    problems = kb_metadata.check_corpus(docs, DATA / "corpus", date(2027, 1, 15))
    assert problems == ["DOC-PIA-03: review date 2026-12-31 has passed"]


def _scores(name):
    golden = eval_gate.load_golden(DATA / "golden/golden.jsonl")
    current = {"DOC-IM-01", "DOC-ID-02", "DOC-PIA-03"}
    return eval_gate.score(golden, eval_gate.load_answers(DATA / f"answers/{name}.jsonl"), current)


def test_production_answers_pass():
    s = _scores("production")
    assert (s.source_recall, s.citation_precision, s.fact_coverage, s.refusal_accuracy) == (1.0, 1.0, 1.0, 1.0)
    assert s.identifier_leaks == 0 and s.p95_latency_ms == 2300
    assert eval_gate.decide(s, None) == (True, [])


def test_candidate_identical_to_production_is_promoted():
    assert eval_gate.decide(_scores("candidate_pass"), _scores("production")) == (True, [])


def test_regressed_candidate_is_blocked_with_reasons():
    s = _scores("candidate_regressed")
    promote, reasons = eval_gate.decide(s, _scores("production"))
    assert not promote
    assert reasons == [
        "BLOCK identifier leaks: 1",
        "BLOCK source_recall 0.800 below 0.90",
        "BLOCK citation_precision 0.800 below 0.95",
        "BLOCK fact_coverage 0.800 below 0.85",
        "BLOCK refusal_accuracy 0.667 below 1.00",
        "BLOCK source_recall regressed by 0.200 (tolerance 0.02)",
        "BLOCK citation_precision regressed by 0.200 (tolerance 0.02)",
        "BLOCK fact_coverage regressed by 0.200 (tolerance 0.03)",
    ]


def test_state_machine_is_structurally_sound():
    assert lint_file(ROOT / "pipeline/state_machine.asl.json") == []


def test_lint_catches_a_shortcut_to_production():
    definition = json.loads((ROOT / "pipeline/state_machine.asl.json").read_text())
    definition["States"]["CorpusClean"]["Choices"][0]["Next"] = "PromoteAlias"
    problems = lint(definition, {"PromoteAlias": ["ScoreAndDecide", "AwaitClinicalSafetySignOff"]})
    assert "PromoteAlias: reachable without passing ScoreAndDecide" in problems
    assert "PromoteAlias: reachable without passing AwaitClinicalSafetySignOff" in problems
