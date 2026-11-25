"""Query engines, router, chat engine, agent and sub-question engine."""

from __future__ import annotations

from datetime import date

from llama_index.core import PropertyGraphIndex, Settings, SummaryIndex, VectorStoreIndex
from llama_index.core.agent.workflow import FunctionAgent
from llama_index.core.chat_engine.types import BaseChatEngine
from llama_index.core.indices.property_graph import SimpleLLMPathExtractor
from llama_index.core.memory import ChatMemoryBuffer
from llama_index.core.postprocessor import SimilarityPostprocessor
from llama_index.core.query_engine import RouterQueryEngine, SubQuestionQueryEngine
from llama_index.core.schema import BaseNode, Document
from llama_index.core.selectors import LLMSingleSelector
from llama_index.core.tools import FunctionTool, QueryEngineTool

from .safe_calc import calculate


def query_engine(index: VectorStoreIndex, top_k: int = 5, min_score: float | None = None):
    postprocessors = [SimilarityPostprocessor(similarity_cutoff=min_score)] if min_score else []
    return index.as_query_engine(
        similarity_top_k=top_k,
        response_mode="compact",
        node_postprocessors=postprocessors,
    )


def property_graph(documents: list[Document], max_paths_per_chunk: int = 10) -> PropertyGraphIndex:
    """Entity graph built by the LLM. One extraction call per chunk."""
    return PropertyGraphIndex.from_documents(
        documents,
        kg_extractors=[SimpleLLMPathExtractor(llm=Settings.llm, max_paths_per_chunk=max_paths_per_chunk, num_workers=4)],
        embed_kg_nodes=True,
    )


def router(vector_index: VectorStoreIndex, nodes: list[BaseNode], graph: PropertyGraphIndex) -> RouterQueryEngine:
    summary_index = SummaryIndex(nodes)
    tools = [
        QueryEngineTool.from_defaults(
            query_engine=query_engine(vector_index),
            name="facts",
            description="Specific facts from the product, pricing and onboarding documents.",
        ),
        QueryEngineTool.from_defaults(
            query_engine=summary_index.as_query_engine(response_mode="tree_summarize"),
            name="summary",
            description="Summaries and overviews that need every document, not a few passages.",
        ),
        QueryEngineTool.from_defaults(
            query_engine=graph.as_query_engine(include_text=True),
            name="relationships",
            description="Who owns, leads, reports to or depends on what: people, teams and services.",
        ),
    ]
    return RouterQueryEngine(selector=LLMSingleSelector.from_defaults(), query_engine_tools=tools, verbose=False)


SYSTEM_PROMPT = (
    "You answer questions about Larkfield Insight using only the retrieved documents. "
    "If the documents do not contain the answer, say so. Name the document each fact comes from."
)


def chat_engine(index: VectorStoreIndex, token_limit: int = 3000) -> BaseChatEngine:
    return index.as_chat_engine(
        chat_mode="condense_plus_context",
        memory=ChatMemoryBuffer.from_defaults(token_limit=token_limit),
        system_prompt=SYSTEM_PROMPT,
        similarity_top_k=4,
    )


def today() -> str:
    """Return today's date in ISO format."""
    return date.today().isoformat()


def agent(handbook_index: VectorStoreIndex, sales_index: VectorStoreIndex) -> FunctionAgent:
    tools = [
        QueryEngineTool.from_defaults(
            query_engine=query_engine(handbook_index),
            name="product_docs",
            description="Product features, editions, pricing and onboarding for Larkfield Insight.",
        ),
        QueryEngineTool.from_defaults(
            query_engine=query_engine(sales_index),
            name="sales_results",
            description="Quarterly revenue, new subscriptions and retention for 2024.",
        ),
        FunctionTool.from_defaults(fn=calculate),
        FunctionTool.from_defaults(fn=today),
    ]
    return FunctionAgent(
        tools=tools,
        llm=Settings.llm,
        system_prompt=SYSTEM_PROMPT + " Use the calculator for any arithmetic instead of doing it yourself.",
    )


def sub_question_engine(handbook_index: VectorStoreIndex, sales_index: VectorStoreIndex) -> SubQuestionQueryEngine:
    tools = [
        QueryEngineTool.from_defaults(
            query_engine=query_engine(handbook_index),
            name="product_docs",
            description="Product features and editions of Larkfield Insight.",
        ),
        QueryEngineTool.from_defaults(
            query_engine=query_engine(sales_index),
            name="sales_results",
            description="Sales results by quarter and by edition for 2024.",
        ),
    ]
    return SubQuestionQueryEngine.from_defaults(query_engine_tools=tools, use_async=True)
