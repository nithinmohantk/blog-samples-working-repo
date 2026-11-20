"""The same lookups with the SDK's tool runner (beta) instead of a hand-written loop.

Shorter, but there is no approval gate, no per-task tool budget and no audit
event per call, which is why the cancel tool is left out here.

    python runner_version.py "What is the status of RX-1002 and has it been dispensed?"
"""
from __future__ import annotations

import json
import os
import sys

import anthropic
from anthropic import beta_tool
from anthropic.lib.tools import ToolError

from rxagent.loop import SYSTEM_PROMPT
from rxagent.rx_service import RxError, RxService

svc = RxService.with_sample_data()


@beta_tool
def get_prescription(rx_id: str) -> str:
    """Get one prescription by its identifier: medication, dose, status, prescriber, repeats.

    Args:
        rx_id: Prescription identifier, for example RX-1002
    """
    try:
        return json.dumps(svc.get(rx_id))
    except RxError as e:
        raise ToolError(str(e)) from e  # sent to Claude as an is_error result with this text


@beta_tool
def get_dispense_events(rx_id: str) -> str:
    """List when and where a prescription was dispensed, newest last.

    Args:
        rx_id: Prescription identifier, for example RX-1002
    """
    try:
        return json.dumps(svc.dispense_events(rx_id))
    except RxError as e:
        raise ToolError(str(e)) from e


def main(prompt: str) -> None:
    workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    client = anthropic.Anthropic(default_headers={"anthropic-workspace-id": workspace} if workspace else None)
    runner = client.beta.messages.tool_runner(
        model="claude-opus-5-5",
        max_tokens=4096,
        max_iterations=6,
        system=SYSTEM_PROMPT,
        tools=[get_prescription, get_dispense_events],
        messages=[{"role": "user", "content": prompt}],
    )
    for message in runner:  # one item per model response
        used = [b.name for b in message.content if b.type == "tool_use"]
        print(f"stop={message.stop_reason} tools={used} in={message.usage.input_tokens} out={message.usage.output_tokens}")
    final = message
    print("\n" + "\n".join(b.text for b in final.content if b.type == "text"))


if __name__ == "__main__":
    main(sys.argv[1])
