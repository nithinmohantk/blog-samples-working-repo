"""A long-horizon agent loop: many turns, on-demand compaction, checkpoints and a cost budget.

Written against anthropic 2.6.0 for Claude Fable 5.2 (claude-fable-5-2) and Claude Opus 5.5.
What changes compared with the short loops in Parts 1 to 4:

- The history is append-only, always. Fable 5.2 enforces the thinking prefix check for every
  account: editing or reordering earlier messages and then replaying a thinking block is a 400.
- When the context passes a threshold we choose, the loop asks the API to compact the whole
  conversation (beta compact-2026-09-04). The signed compaction block replaces the history and
  the agent continues from the summary plus whatever the back end says is left to do.
- Progress lives in the back end, not in the conversation, so nothing depends on the summary
  being perfect: the agent can always call get_progress.
- After every turn the loop writes a checkpoint (messages and back-end state), so a crash or a
  deliberate stop can resume from the last completed turn with the history byte-for-byte intact.
- Cost is tracked across usage.iterations, which include the compaction calls, and the task stops
  when it reaches its budget.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from . import tools as toolbox
from .data import AUDIT_DATE, OVERDUE_DAYS, STALE_DAYS
from .service import AuditError, AuditService

log = logging.getLogger("auditagent")

BETAS = ["compact-2026-09-04"]

SYSTEM_PROMPT = f"""You are auditing the repeat prescriptions of a general practice. The audit date is {AUDIT_DATE.isoformat()}. All data is synthetic.

Check every prescription in the audit list against these rules. Rules apply to active prescriptions only; cancelled ones are reviewed with no findings.
- NO_REPEATS: repeats_remaining is 0.
- OVERDUE: repeats_remaining is above 0 and more than {OVERDUE_DAYS} days have passed since the last dispense (or since the issue date if it was never dispensed).
- STALE: issued more than {STALE_DAYS} days before the audit date.
- DUPLICATE_CLASS: the same patient has two or more active prescriptions for medicines in the same therapeutic class (for example two statins). Record the finding on each prescription involved.

How to work:
- You own this audit and must finish all of it. Do not stop until get_progress shows nothing remaining, then reply with a short summary of the findings by rule.
- Start with get_progress. Work in batches: fetch details for up to 4 prescriptions at a time, record any findings with record_findings, then mark the batch reviewed.
- The duplicate rule needs every prescription of a patient. Check it per patient once you have seen all of their prescriptions.
- Count days exactly from the dates given. Record a finding only when a rule is met; a note must give the dates or counts that triggered it.
- Your earlier conversation may be replaced by a summary. If you are unsure what is done, call get_progress; the register is the record, not your memory.
- Every few batches, write one short progress line for the reader."""

COMPACTION_INSTRUCTIONS = (
    "Summarize this audit for the agent that will continue it. Keep: the audit rules in force, which "
    "prescriptions and patients have been reviewed, any patient whose prescriptions are only partly seen and "
    "the medicines seen so far for them (needed for the duplicate-class rule), and findings recorded. "
    "The findings register and get_progress remain available. Do not call any tools; respond with the "
    "summary text only.")

# USD per million tokens. Cache writes are the 5-minute TTL.
PRICES: dict[str, dict[str, float]] = {
    "claude-fable-5-2": {"input": 8.0, "output": 40.0, "cache_write": 10.0, "cache_read": 0.20},
    "claude-opus-5-5": {"input": 4.0, "output": 20.0, "cache_write": 5.0, "cache_read": 0.20},
}


class MessagesClient(Protocol):
    beta: Any


@dataclass
class LongRunConfig:
    model: str = "claude-fable-5-2"
    effort: str = "high"              # Fable 5.2 default; set explicitly so a model change does not change it
    max_tokens: int = 16_000
    max_turns: int = 80
    budget_usd: float = 4.0
    compact_at_tokens: int = 40_000   # our threshold, far below the 1M window: cost, not capacity, is the limit
    stop_after_turns: int | None = None  # simulate an interruption for the resume demo


@dataclass
class Usage:
    input: int = 0
    output: int = 0
    cache_write: int = 0
    cache_read: int = 0

    def add(self, other: "Usage") -> None:
        self.input += other.input; self.output += other.output
        self.cache_write += other.cache_write; self.cache_read += other.cache_read

    def cost(self, model: str) -> float:
        p = PRICES[model]
        return (self.input * p["input"] + self.output * p["output"] + self.cache_write * p["cache_write"]
                + self.cache_read * p["cache_read"]) / 1_000_000


def billed_usage(usage: Any) -> Usage:
    """Sum usage.iterations when present (it includes compaction); otherwise the top-level fields."""
    items = getattr(usage, "iterations", None) or [usage]
    u = Usage()
    for it in items:
        u.add(Usage(int(getattr(it, "input_tokens", 0) or 0), int(getattr(it, "output_tokens", 0) or 0),
                    int(getattr(it, "cache_creation_input_tokens", 0) or 0),
                    int(getattr(it, "cache_read_input_tokens", 0) or 0)))
    return u


def context_tokens(usage: Any) -> int:
    """How big the next request will be, roughly: everything this request read plus what it wrote."""
    return sum(int(getattr(usage, k, 0) or 0) for k in
               ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens"))


def _as_dicts(content: list[Any]) -> list[dict[str, Any]]:
    """Blocks exactly as returned, as plain dicts: safe to checkpoint and to send back."""
    return [b if isinstance(b, dict) else b.to_dict() for b in content]


@dataclass
class RunState:
    messages: list[dict[str, Any]] = field(default_factory=list)
    turns: int = 0
    compactions: int = 0
    tool_calls: int = 0
    usage: Usage = field(default_factory=Usage)
    started_at: float = field(default_factory=time.time)
    elapsed_s: float = 0.0
    events: list[dict[str, Any]] = field(default_factory=list)

    def save(self, path: Path, svc: AuditService, model: str) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"model": model, "messages": self.messages, "turns": self.turns,
                                   "compactions": self.compactions, "tool_calls": self.tool_calls,
                                   "usage": self.usage.__dict__, "elapsed_s": self.elapsed_s,
                                   "events": self.events, "service": svc.to_state()}))
        tmp.replace(path)  # atomic: a crash mid-write never leaves a half checkpoint

    @classmethod
    def load(cls, path: Path, svc: AuditService) -> tuple["RunState", str]:
        raw = json.loads(path.read_text())
        if raw["service"].get("patients", 16) != svc.patients:
            raise ValueError(f"checkpoint is for {raw['service'].get('patients')} patients, not {svc.patients}")
        svc.load_state(raw["service"])
        st = cls(raw["messages"], raw["turns"], raw["compactions"], raw["tool_calls"], Usage(**raw["usage"]),
                 elapsed_s=raw["elapsed_s"], events=raw["events"])
        return st, raw["model"]


@dataclass
class RunResult:
    outcome: str          # completed | budget | turn_limit | stopped | refusal | truncated
    text: str
    state: RunState


def _execute(svc: AuditService, block: Any) -> dict[str, Any]:
    handler = toolbox.HANDLERS.get(block["name"])
    out: dict[str, Any] = {"type": "tool_result", "tool_use_id": block["id"]}
    if handler is None:
        out.update(content=f"Unknown tool {block['name']}.", is_error=True)
        return out
    try:
        out["content"] = toolbox.to_result_text(handler(svc, block["input"]))
    except AuditError as e:
        out.update(content=str(e), is_error=True)
    except Exception:
        ref = uuid.uuid4().hex[:8]
        log.exception(json.dumps({"event": "tool_crashed", "tool": block["name"], "ref": ref}))
        out.update(content=f"Internal error (reference {ref}). Do not retry this call.", is_error=True)
    return out


def _request(client: MessagesClient, cfg: LongRunConfig, messages: list[dict[str, Any]], **extra: Any) -> Any:
    return client.beta.messages.create(
        betas=BETAS, model=cfg.model, max_tokens=cfg.max_tokens, system=SYSTEM_PROMPT,
        tools=toolbox.DEFINITIONS, messages=messages,
        thinking={"type": "adaptive"}, output_config={"effort": cfg.effort}, **extra)


def _compact(client: MessagesClient, cfg: LongRunConfig, st: RunState) -> bool:
    """Replace the history with a signed summary. Returns False (history untouched) if none came back."""
    # cache_control matters here: without a breakpoint the compaction request cannot read the
    # cached history, and the whole context is billed at the full input price (the first live run
    # paid about $0.35 of uncached input on Fable 5.2 for a 42k-token history).
    resp = _request(client, cfg, st.messages, cache_control={"type": "ephemeral"},
                    compaction={"type": "summarize", "instructions": COMPACTION_INSTRUCTIONS})
    used = billed_usage(resp.usage)
    st.usage.add(used)
    block = next((b for b in resp.content if b.type == "compaction"), None)
    if resp.stop_reason != "compaction" or block is None or block.content is None:
        st.events.append({"event": "compaction_skipped", "turn": st.turns, "stop_reason": resp.stop_reason})
        return False
    st.messages = [{"role": "assistant", "content": _as_dicts([block])},
                   {"role": "user", "content": "Continue the audit from the summary. Call get_progress first."}]
    st.compactions += 1
    st.events.append({"event": "compacted", "turn": st.turns, "summary_chars": len(block.content),
                      "input": used.input, "cache_read": used.cache_read, "cache_write": used.cache_write,
                      "output": used.output, "cost": round(used.cost(cfg.model), 4)})
    return True


def run(client: MessagesClient, svc: AuditService, cfg: LongRunConfig, checkpoint: Path,
        state: RunState | None = None) -> RunResult:
    st = state or RunState(messages=[{"role": "user", "content": "Run the repeat-prescription audit."}])
    turns_this_session = 0
    session_start = time.perf_counter()
    base_elapsed = st.elapsed_s

    while True:
        if st.turns >= cfg.max_turns:
            return RunResult("turn_limit", "", st)
        if st.usage.cost(cfg.model) >= cfg.budget_usd:
            return RunResult("budget", "", st)
        if cfg.stop_after_turns is not None and turns_this_session >= cfg.stop_after_turns:
            return RunResult("stopped", "", st)

        resp = _request(client, cfg, st.messages, cache_control={"type": "ephemeral"})
        st.turns += 1
        turns_this_session += 1
        st.usage.add(billed_usage(resp.usage))
        content = _as_dicts(resp.content)
        st.messages.append({"role": "assistant", "content": content})  # append-only, exactly as returned
        uses = [b for b in content if b["type"] == "tool_use"]
        st.tool_calls += len(uses)
        st.events.append({"event": "turn", "turn": st.turns, "stop_reason": resp.stop_reason,
                          "tools": [u["name"] for u in uses], "context": context_tokens(resp.usage),
                          "cost": round(st.usage.cost(cfg.model), 4),
                          "text": " ".join(b.get("text", "") for b in content if b["type"] == "text")[:200]})
        log.info(json.dumps(st.events[-1]))

        if resp.stop_reason == "tool_use":
            st.messages.append({"role": "user", "content": [_execute(svc, u) for u in uses]})
            st.elapsed_s = base_elapsed + time.perf_counter() - session_start
            if context_tokens(resp.usage) > cfg.compact_at_tokens:
                _compact(client, cfg, st)
            st.save(checkpoint, svc, cfg.model)
            continue

        st.elapsed_s = base_elapsed + time.perf_counter() - session_start
        st.save(checkpoint, svc, cfg.model)
        text = " ".join(b.get("text", "") for b in content if b["type"] == "text").strip()
        if resp.stop_reason == "end_turn" and svc.progress()["remaining"] > 0:
            # The docs warn that long tasks can end early. The register, not the model, decides.
            st.messages.append({"role": "user", "content": "The audit is not finished: get_progress shows "
                                f"{svc.progress()['remaining']} prescriptions remaining. Continue until none remain."})
            st.events.append({"event": "nudged", "turn": st.turns, "remaining": svc.progress()["remaining"]})
            continue
        outcome = {"end_turn": "completed", "refusal": "refusal", "max_tokens": "truncated"}.get(
            resp.stop_reason, resp.stop_reason)
        return RunResult(outcome, text, st)
