"""Layer 4: a real browser against the two running services. Usage: python e2e/run.py <web url> <agent url> <output dir>

Chromium drives the Blazor page; the payment stand-in is read over HTTP after each step.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

from playwright.sync_api import Page, expect, sync_playwright

WEB, AGENT, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
results: list[dict] = []


def ledger() -> dict:
    with urllib.request.urlopen(f"{AGENT}/ledger", timeout=10) as response:
        return json.load(response)


def ask(page: Page, text: str) -> None:
    box = page.locator("textarea.sc-ai-input__textarea")
    expect(box).to_be_enabled(timeout=15000)
    box.fill(text)
    page.locator("button.sc-ai-input__send").click()


def step(name: str, check) -> None:
    started = time.monotonic()
    try:
        detail = check()
        results.append({"step": name, "ok": True, "seconds": round(time.monotonic() - started, 2), "detail": detail})
    except Exception as error:  # a failed step is recorded and the run goes on, so one report shows everything
        results.append({"step": name, "ok": False, "seconds": round(time.monotonic() - started, 2), "detail": str(error).splitlines()[0][:300]})
    print(("ok   " if results[-1]["ok"] else "FAIL ") + f"{name}: {results[-1]['detail']}")


def main() -> int:
    urllib.request.urlopen(urllib.request.Request(f"{AGENT}/reset", method="POST"), timeout=10).close()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1376, "height": 768})
        hosts: dict[str, int] = {}
        page.on("request", lambda request: hosts.__setitem__(request.url.split("/")[2], hosts.get(request.url.split("/")[2], 0) + 1))
        page.on("websocket", lambda socket: hosts.__setitem__("websocket " + socket.url.split("/")[2], 1))
        page.goto(WEB)

        def order_card():
            ask(page, "Where is order O-1001?")
            card = page.locator(".order-card[data-order='O-1001']")
            expect(card).to_contain_text("Synthetic kettle", timeout=15000)
            expect(page.get_by_text("Here is the order.")).to_be_visible(timeout=15000)
            page.screenshot(path=f"{OUT}/shot-1-order-card.png")
            return card.inner_text().replace("\n", " | ")

        def approval_shown():
            ask(page, "Refund order O-1003")
            approve_button = page.locator(".sc-ai-approval").last.get_by_role("button", name="Approve")
            expect(approve_button).to_be_visible(timeout=15000)
            approve_button.scroll_into_view_if_needed()
            page.wait_for_timeout(300)
            page.screenshot(path=f"{OUT}/shot-2-approval.png")
            state = ledger()
            assert state["attempts"] == 0, state
            return f"buttons shown; refund attempts so far: {state['attempts']}"

        def approve():
            page.locator(".sc-ai-approval").last.get_by_role("button", name="Approve").click()
            expect(page.get_by_text("The refund is recorded.")).to_be_visible(timeout=15000)
            state = ledger()
            assert [r["orderId"] for r in state["refunds"]] == ["O-1003"], state
            return f"refunds: {[(r['orderId'], r['amount']) for r in state['refunds']]}"

        def reject():
            ask(page, "Refund order O-1002")
            page.locator(".sc-ai-approval").last.get_by_role("button", name="Reject").click()
            expect(page.get_by_text("No refund was made")).to_be_visible(timeout=15000)
            state = ledger()
            assert len(state["refunds"]) == 1 and state["attempts"] == 1, state
            return f"refunds: {len(state['refunds'])}, attempts: {state['attempts']}"

        def approve_again():
            ask(page, "Refund order O-1003")
            page.locator(".sc-ai-approval").last.get_by_role("button", name="Approve").click()
            expect(page.get_by_text("refunded earlier")).to_be_visible(timeout=15000)
            state = ledger()
            assert len(state["refunds"]) == 1 and state["attempts"] == 2, state
            return f"refunds: {len(state['refunds'])}, attempts: {state['attempts']}"

        def state_from_agent():
            ask(page, "Draft a reply for order O-1001")
            reply = page.locator(".reply-panel__reply")
            expect(reply).to_have_value("Hi Test Customer One, good news: order O-1001 (Synthetic kettle) is delivered with Example Post.", timeout=15000)
            return reply.input_value()

        def state_to_agent():
            expect(page.locator("textarea.sc-ai-input__textarea")).to_be_enabled(timeout=15000)
            signature = page.locator(".reply-panel__signature")
            signature.fill("Sam, Order Desk")
            signature.press("Tab")
            ask(page, "Draft a formal reply for order O-1001")
            reply = page.locator(".reply-panel__reply")
            expect(reply).to_have_value("Dear Test Customer One, your order O-1001 (Synthetic kettle) is recorded as delivered with Example Post. Regards, Sam, Order Desk", timeout=15000)
            expect(page.locator("textarea.sc-ai-input__textarea")).to_be_enabled(timeout=15000)
            page.wait_for_timeout(300)
            page.screenshot(path=f"{OUT}/shot-3-shared-state.png")
            return reply.input_value()

        def stop():
            expect(page.locator("textarea.sc-ai-input__textarea")).to_be_enabled(timeout=15000)
            ask(page, "Explain the refund policy")
            button = page.locator("button.desk-stop")
            expect(button).to_be_visible(timeout=15000)
            page.wait_for_timeout(600)
            button.click()
            expect(button).to_be_hidden(timeout=15000)
            expect(page.locator("textarea.sc-ai-input__textarea")).to_be_enabled(timeout=15000)
            page.wait_for_timeout(1500)
            with open(f"{OUT}/e2e-wire.jsonl", encoding="utf-8") as handle:
                last = json.loads(handle.readlines()[-1])
            assert last["Completed"] is False and "RUN_FINISHED" not in last["Events"], last["Events"][-3:]
            return f"server stream ended after {len(last['Events'])} events, no RUN_FINISHED"

        step("order card from a backend tool", order_card)
        step("refund waits for approval", approval_shown)
        step("approve pays once", approve)
        step("reject pays nothing", reject)
        step("approving the same refund again pays nothing more", approve_again)
        step("state from the agent fills the panel", state_from_agent)
        step("state edited by the user reaches the agent", state_to_agent)
        step("stop ends the run on the server", stop)

        def browser_never_calls_the_agent():
            agent_host = AGENT.split("/")[2]
            assert not any(agent_host in host for host in hosts), hosts
            return f"hosts the browser talked to: {sorted(hosts)}"

        step("the browser never calls the agent service", browser_never_calls_the_agent)
        browser.close()

    with open(f"{OUT}/e2e.json", "w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=1)
    passed = sum(r["ok"] for r in results)
    print(f"{passed} of {len(results)} browser steps passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
