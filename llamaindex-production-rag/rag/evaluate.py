"""Evaluate a query engine with LLM judges and with plain string checks.

The judges (faithfulness, relevancy, correctness) use the configured LLM.
Each question also carries facts that must appear in the answer, checked in
code, so a regression in retrieval shows up even when a judge is lenient.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

from llama_index.core.evaluation import (
    BatchEvalRunner,
    CorrectnessEvaluator,
    FaithfulnessEvaluator,
    RelevancyEvaluator,
)


@dataclass(frozen=True)
class EvalCase:
    question: str
    reference: str
    must_contain: tuple[str, ...]


CASES: list[EvalCase] = [
    EvalCase("What is the monthly price of the Team edition?", "EUR 1,150 per month, billed annually.", ("1,150",)),
    EvalCase("How many shipment events per month does the Starter edition include?", "50,000 shipment events.", ("50,000",)),
    EvalCase("Which carriers have connectors?", "DHL, UPS, FedEx, DPD, An Post and GLS.", ("DHL", "An Post", "GLS")),
    EvalCase("Can the data residency region be changed after a workspace is created?", "No, it cannot be changed later.", ("cannot",)),
    EvalCase("How far back do carrier connectors back-fill events?", "The previous 90 days.", ("90",)),
    EvalCase("Which editions support single sign-on?", "Team and Enterprise only.", ("Team", "Enterprise")),
]


@dataclass
class CaseResult:
    question: str
    answer: str
    faithful: bool | None
    relevant: bool | None
    correctness: float | None
    missing: list[str]


def string_check(answer: str, must_contain: tuple[str, ...]) -> list[str]:
    normalised = re.sub(r"\s+", " ", answer)
    return [fact for fact in must_contain if fact.lower() not in normalised.lower()]


async def evaluate(query_engine, cases: list[EvalCase] = CASES, workers: int = 4) -> list[CaseResult]:
    runner = BatchEvalRunner(
        {"faithfulness": FaithfulnessEvaluator(), "relevancy": RelevancyEvaluator()},
        workers=workers,
    )
    questions = [c.question for c in cases]
    responses = [await query_engine.aquery(q) for q in questions]
    judged = await runner.aevaluate_responses(questions, responses=responses)
    correctness = CorrectnessEvaluator()
    results = []
    for i, case in enumerate(cases):
        answer = str(responses[i])
        scored = await correctness.aevaluate(query=case.question, response=answer, reference=case.reference)
        results.append(
            CaseResult(
                question=case.question,
                answer=answer,
                faithful=judged["faithfulness"][i].passing,
                relevant=judged["relevancy"][i].passing,
                correctness=scored.score,
                missing=string_check(answer, case.must_contain),
            )
        )
    return results


def run(query_engine, cases: list[EvalCase] = CASES) -> list[CaseResult]:
    return asyncio.run(evaluate(query_engine, cases))
