"""Run every example in the article against a live model and record timings.

  python run.py ingest --store chroma     # run twice: the second run writes 0 nodes
  python run.py query "What does the Team edition cost?"
  python run.py router
  python run.py chat
  python run.py agent
  python run.py subq
  python run.py eval
  python run.py all                       # everything above, results in results/run.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from pathlib import Path

from rag import engines, evaluate, ingest
from rag.settings import configure

ROOT = Path(__file__).resolve().parent
STORAGE = ROOT / "storage"
RESULTS = ROOT / "results"
log = logging.getLogger("rag")
RECORD: dict[str, object] = {}


def timed(name: str, fn, *args, **kwargs):
    start = time.perf_counter()
    result = fn(*args, **kwargs)
    elapsed = time.perf_counter() - start
    RECORD.setdefault("timings_s", {})[name] = round(elapsed, 2)
    print(f"[{name}] {elapsed:.2f} s")
    return result


_STORES: dict[tuple[str, str], object] = {}


def vector_store(store: str, collection: str):
    """One client per path for the life of the process (local Qdrant locks its folder)."""
    key = (store, collection)
    if key not in _STORES:
        make = ingest.chroma_store if store == "chroma" else ingest.qdrant_store
        _STORES[key] = make(STORAGE / store / collection, collection=collection)
    return _STORES[key]


def indexes(store: str = "chroma"):
    handbook_docs = ingest.load_documents(subdir="handbook")
    sales_docs = ingest.load_documents(subdir="sales")
    handbook = ingest.ingest(handbook_docs, vector_store(store, "handbook"), STORAGE / store / "handbook-docstore.json")
    sales = ingest.ingest(sales_docs, vector_store(store, "sales"), STORAGE / store / "sales-docstore.json")
    return handbook_docs, sales_docs, handbook, sales


def cmd_ingest(args) -> None:
    handbook_docs, sales_docs, handbook, sales = timed(f"ingest_{args.store}", indexes, args.store)
    print(f"documents: {len(handbook_docs)} handbook, {len(sales_docs)} sales")
    print(f"nodes written: {handbook.nodes_written} handbook, {sales.nodes_written} sales")
    RECORD[f"ingest_{args.store}"] = {"handbook_nodes_written": handbook.nodes_written, "sales_nodes_written": sales.nodes_written}


def show_sources(response) -> list[dict]:
    sources = []
    for node in response.source_nodes:
        score = f"{node.score:.3f}" if node.score is not None else "-"
        print(f"  {score}  {node.metadata.get('file_name')}: {node.text[:70].strip()!r}")
        sources.append({"file": node.metadata.get("file_name"), "score": node.score})
    return sources


def cmd_query(args) -> None:
    _, _, handbook, _ = indexes()
    engine = engines.query_engine(handbook.index)
    question = args.question or "What does the Team edition cost, and how many shipment events does it include?"
    response = timed("query", engine.query, question)
    print(f"Q: {question}\nA: {response}")
    RECORD["query"] = {"question": question, "answer": str(response), "sources": show_sources(response)}


ROUTER_QUESTIONS = [
    "What is the overage charge per 1,000 events on the Team edition?",
    "Give me an overview of what the Larkfield Insight documentation covers.",
    "Who approves new carrier connectors, and who does that person report to?",
]


def cmd_router(args) -> None:
    handbook_docs = ingest.load_documents(subdir="handbook")
    _, _, handbook, _ = indexes()
    graph = timed("property_graph_build", engines.property_graph, handbook_docs)
    engine = engines.router(handbook.index, ingest.split(handbook_docs), graph)
    rows = []
    for i, question in enumerate(ROUTER_QUESTIONS):
        response = timed(f"router_{i}", engine.query, question)
        selected = response.metadata.get("selector_result") if response.metadata else None
        choice = [s.index for s in selected.selections] if selected else None
        print(f"Q: {question}\n  tool index {choice}\nA: {response}\n")
        rows.append({"question": question, "selected": choice, "answer": str(response)})
    RECORD["router"] = rows


def cmd_chat(args) -> None:
    _, _, handbook, _ = indexes()
    chat = engines.chat_engine(handbook.index)
    turns = ["Which editions support single sign-on?", "And how much does the cheaper of those cost per month?"]
    rows = []
    for i, turn in enumerate(turns):
        response = timed(f"chat_{i}", chat.chat, turn)
        print(f"User: {turn}\nAssistant: {response}\n")
        rows.append({"user": turn, "assistant": str(response)})
    RECORD["chat"] = rows


AGENT_QUESTION = "What was Q3 2024 revenue, and what was the growth rate compared with Q2 2024?"


def cmd_agent(args) -> None:
    _, _, handbook, sales = indexes()
    agent = engines.agent(handbook.index, sales.index)

    async def go():
        handler = agent.run(user_msg=AGENT_QUESTION)
        calls = []
        from llama_index.core.agent.workflow import ToolCallResult

        async for event in handler.stream_events():
            if isinstance(event, ToolCallResult):
                calls.append({"tool": event.tool_name, "input": event.tool_kwargs, "output": str(event.tool_output)[:200]})
                print(f"  tool {event.tool_name}({event.tool_kwargs}) -> {str(event.tool_output)[:120]!r}")
        return await handler, calls

    response, calls = timed("agent", asyncio.run, go())
    print(f"Q: {AGENT_QUESTION}\nA: {response}")
    RECORD["agent"] = {"question": AGENT_QUESTION, "answer": str(response), "tool_calls": calls}


SUBQ_QUESTION = "Which edition sells best, what features does it include, and what share of 2024 revenue did it produce?"


def cmd_subq(args) -> None:
    _, _, handbook, sales = indexes()
    engine = engines.sub_question_engine(handbook.index, sales.index)
    response = timed("sub_question", engine.query, SUBQ_QUESTION)
    subs = [str(n.text.splitlines()[0]) for n in response.source_nodes]
    print(f"Q: {SUBQ_QUESTION}\nA: {response}")
    for s in subs:
        print(f"  {s[:150]}")
    RECORD["sub_question"] = {"question": SUBQ_QUESTION, "answer": str(response), "sub_questions": subs}


def cmd_eval(args) -> None:
    _, _, handbook, _ = indexes()
    results = timed("evaluation", evaluate.run, engines.query_engine(handbook.index))
    rows = []
    for r in results:
        print(f"{r.question}\n  faithful={r.faithful} relevant={r.relevant} correctness={r.correctness} missing={r.missing}")
        rows.append(r.__dict__)
    RECORD["evaluation"] = rows


def cmd_all(args) -> None:
    for name, fn in [("ingest", cmd_ingest), ("ingest_again", cmd_ingest), ("query", cmd_query), ("router", cmd_router),
                     ("chat", cmd_chat), ("agent", cmd_agent), ("subq", cmd_subq), ("eval", cmd_eval)]:
        print(f"\n===== {name}")
        fn(args)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["ingest", "query", "router", "chat", "agent", "subq", "eval", "all"])
    parser.add_argument("question", nargs="?")
    parser.add_argument("--store", choices=["chroma", "qdrant"], default="chroma")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    config = configure()
    RECORD["models"] = {"provider": config.provider, "chat": config.chat_model, "model": config.model_name, "embed": config.embed_model}
    {"ingest": cmd_ingest, "query": cmd_query, "router": cmd_router, "chat": cmd_chat, "agent": cmd_agent,
     "subq": cmd_subq, "eval": cmd_eval, "all": cmd_all}[args.command](args)
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"run-{args.command}.json"
    out.write_text(json.dumps(RECORD, indent=2, default=str))
    print(f"\nwritten {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
