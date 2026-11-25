"""Offline tests: no model calls. Embeddings are a fixed-size mock."""

import pytest
from llama_index.core import Document, Settings
from llama_index.core.embeddings import MockEmbedding
from llama_index.core.llms import MockLLM

from rag import evaluate, ingest
from rag.safe_calc import calculate, evaluate as calc
from rag.settings import load_config


@pytest.fixture(autouse=True)
def mock_models():
    Settings.embed_model = MockEmbedding(embed_dim=8)
    Settings.llm = MockLLM()


def test_calculator_does_arithmetic():
    assert calculate("(4830000 - 4200000) / 4200000 * 100") == "15"
    assert calculate("2 ** 10") == "1024"
    assert calculate("1,150 * 12") == "13800"


@pytest.mark.parametrize("expr", ["__import__('os').system('id')", "open('/etc/passwd')", "[1, 2]", "x + 1", "9 ** 999999"])
def test_calculator_refuses_anything_but_arithmetic(expr):
    assert calculate(expr).startswith("Error")


def test_calculator_errors_are_strings_not_exceptions():
    assert calculate("1 / 0").startswith("Error")
    with pytest.raises(ValueError):
        calc("a" * 300)


def test_documents_carry_collection_metadata():
    docs = ingest.load_documents()
    assert len(docs) == 5
    assert {d.metadata["collection"] for d in docs} == {"handbook", "sales"}
    assert all(d.id_.endswith(".md") for d in docs)


def test_split_respects_chunk_size():
    nodes = ingest.split(ingest.load_documents(subdir="handbook"))
    assert len(nodes) >= 4
    assert all(n.metadata["file_name"].endswith(".md") for n in nodes)


@pytest.mark.parametrize("backend", ["chroma", "qdrant"])
def test_reingest_skips_unchanged_documents(tmp_path, backend):
    docs = ingest.load_documents(subdir="handbook")
    make = ingest.chroma_store if backend == "chroma" else ingest.qdrant_store
    store = make(tmp_path / "store")  # one client per process, as in a long-running service
    first = ingest.ingest(docs, store, tmp_path / "docstore.json")
    assert first.nodes_written > 0
    second = ingest.ingest(docs, store, tmp_path / "docstore.json")
    assert second.nodes_written == 0
    edited = Document(text=docs[0].text + "\nNew paragraph.", id_=docs[0].id_, metadata=docs[0].metadata)
    third = ingest.ingest([edited] + docs[1:], store, tmp_path / "docstore.json")
    assert 0 < third.nodes_written < first.nodes_written
    retriever = third.index.as_retriever(similarity_top_k=3)
    assert len(retriever.retrieve("pricing")) == 3


def test_string_check_reports_missing_facts():
    assert evaluate.string_check("EUR 1,150 per month", ("1,150",)) == []
    assert evaluate.string_check("about a thousand euro", ("1,150",)) == ["1,150"]


def test_settings_fail_fast_without_configuration(monkeypatch):
    for name in ["AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_CHAT_DEPLOYMENT", "AZURE_OPENAI_EMBED_DEPLOYMENT", "OPENAI_API_KEY"]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("RAG_PROVIDER", "azure")
    with pytest.raises(RuntimeError, match="AZURE_OPENAI_ENDPOINT"):
        load_config()
    monkeypatch.setenv("RAG_PROVIDER", "openai")
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        load_config()
