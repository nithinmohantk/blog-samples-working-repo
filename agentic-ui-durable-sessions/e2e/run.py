"""A real browser, two services, and the things that end a page: reload, restart, a second tab.
Usage: python e2e/run.py <output dir>

This script starts and stops the services itself, because several steps are "stop it and start it again".
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.request

from playwright.sync_api import Page, expect, sync_playwright

OUT = sys.argv[1]
WEB, AGENT = "http://127.0.0.1:5120", "http://127.0.0.1:5121"
DATA = os.path.join(OUT, "data")
BOX = "textarea.sc-ai-input__textarea"
results: list[dict] = []
processes: dict[str, subprocess.Popen] = {}


def start(name: str, extra: dict[str, str] | None = None) -> None:
    project, url = ("src/Desk.Agent", AGENT) if name == "agent" else ("src/Desk.Web", WEB)
    env = dict(os.environ, ASPNETCORE_ENVIRONMENT="Development", DESK_DATA=DATA, AGENT_URL=AGENT, DESK_WIRE_LOG=os.path.join(OUT, "e2e-wire.jsonl"), **(extra or {}))
    log = open(os.path.join(OUT, f"{name}.log"), "a", encoding="utf-8")
    processes[name] = subprocess.Popen(
        ["dotnet", "run", "--project", project, "-c", "Release", "--no-build", "--no-launch-profile", "--urls", url],
        env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    probe = f"{AGENT}/ledger" if name == "agent" else f"{WEB}/"
    for _ in range(120):
        try:
            urllib.request.urlopen(probe, timeout=2).close()
            return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"{name} did not start")


def stop(name: str) -> None:
    process = processes.pop(name)
    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    process.wait(timeout=20)


def ledger() -> dict:
    with urllib.request.urlopen(f"{AGENT}/ledger", timeout=10) as response:
        return json.load(response)


def wire() -> list[dict]:
    with open(os.path.join(OUT, "e2e-wire.jsonl"), encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def ask(page: Page, text: str) -> None:
    box = page.locator(BOX)
    expect(box).to_be_enabled(timeout=20000)
    box.fill(text)
    page.locator("button.sc-ai-input__send").click()


def reload(page: Page) -> None:
    page.reload()
    expect(page.locator(BOX)).to_be_visible(timeout=20000)
    page.wait_for_timeout(700)


current_page: list[Page] = []


def step(name: str, check) -> None:
    started = time.monotonic()
    try:
        detail = check()
        results.append({"step": name, "ok": True, "seconds": round(time.monotonic() - started, 2), "detail": detail})
    except Exception as error:  # a failed step is recorded and the run goes on, so one report shows everything
        results.append({"step": name, "ok": False, "seconds": round(time.monotonic() - started, 2), "detail": " / ".join(str(error).splitlines()[:6])[:700]})
        try:
            current_page[0].screenshot(path=f"{OUT}/failed-{len(results)}.png")
            with open(f"{OUT}/failed-{len(results)}.txt", "w", encoding="utf-8") as handle:
                handle.write(current_page[0].locator("body").inner_text())
        except Exception:
            pass
    print(("ok   " if results[-1]["ok"] else "FAIL ") + f"{name}: {results[-1]['detail']}")


def main() -> int:
    os.makedirs(DATA, exist_ok=True)
    start("agent")
    start("web")
    urllib.request.urlopen(urllib.request.Request(f"{AGENT}/reset", method="POST"), timeout=10).close()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1376, "height": 768})
        page = context.new_page()
        current_page.append(page)

        def address():
            page.goto(WEB)
            page.wait_for_url("**/c/*", timeout=20000)
            ask(page, "Where is order O-1001?")
            expect(page.get_by_text("Here is the order.")).to_be_visible(timeout=20000)
            return f"the conversation has its own address: /c/{'x' * 32} ({len(page.url.rsplit('/', 1)[1])} characters, random)"

        def reload_keeps_it():
            reload(page)
            card = page.locator(".order-card[data-order='O-1001']")
            expect(card).to_contain_text("Synthetic kettle", timeout=20000)
            expect(page.get_by_text("Here is the order.")).to_be_visible()
            return f"after a reload: order cards {page.locator('.order-card').count()}, text of the answer present"

        def state_comes_back():
            ask(page, "Draft a reply for order O-1001")
            reply = page.locator(".reply-panel__reply")
            expect(reply).to_have_value("Hi Test Customer One, good news: order O-1001 (Synthetic kettle) is delivered with Example Post.", timeout=20000)
            expect(page.locator(BOX)).to_be_enabled(timeout=20000)
            signature = page.locator(".reply-panel__signature")
            signature.fill("Sam, Order Desk")
            signature.press("Tab")
            page.wait_for_timeout(500)
            reload(page)
            expect(page.locator(".reply-panel__reply")).to_have_value("Hi Test Customer One, good news: order O-1001 (Synthetic kettle) is delivered with Example Post.", timeout=20000)
            expect(page.locator(".reply-panel__signature")).to_have_value("Sam, Order Desk")
            return "after a reload the draft reply and the signature typed by the user are both in the panel"

        def approval_survives_reload():
            ask(page, "Refund order O-1003")
            expect(page.locator(".sc-ai-approval").last.get_by_role("button", name="Approve")).to_be_visible(timeout=20000)
            reload(page)
            restored = page.locator(".desk-restored-approval").last
            expect(restored.get_by_role("button", name="Approve")).to_be_visible(timeout=20000)
            restored.scroll_into_view_if_needed()
            page.wait_for_timeout(300)
            page.screenshot(path=f"{OUT}/shot-1-restored-approval.png")
            assert ledger()["attempts"] == 0
            restored.get_by_role("button", name="Approve").click()
            expect(page.get_by_text("The refund is recorded.")).to_be_visible(timeout=20000)
            state = ledger()
            assert [r["orderId"] for r in state["refunds"]] == ["O-1003"], state
            return f"the approval came back with buttons; Approve after the reload paid once: {[(r['orderId'], r['amount']) for r in state['refunds']]}"

        def answered_stays_answered():
            reload(page)
            expect(page.get_by_text("The refund is recorded.")).to_be_visible(timeout=20000)
            buttons = page.locator(".sc-ai-approval").get_by_role("button", name="Approve").count()
            answered = page.locator(".desk-restored-approval__answered").count()
            assert buttons == 0, buttons
            return f"after another reload: Approve buttons {buttons}, approvals shown as answered {answered}"

        def web_restart():
            stop("web")
            start("web")
            reload(page)
            expect(page.locator(".order-card[data-order='O-1001']")).to_be_visible(timeout=20000)
            expect(page.get_by_text("The refund is recorded.")).to_be_visible()
            expect(page.locator(".reply-panel__signature")).to_have_value("Sam, Order Desk")
            return "the web app was stopped and started; the same address shows the whole conversation and the panel"

        def agent_restart():
            ask(page, "Refund order O-1002")
            expect(page.locator(".sc-ai-approval").last.get_by_role("button", name="Approve")).to_be_visible(timeout=20000)
            stop("agent")
            start("agent")
            reload(page)
            restored = page.locator(".desk-restored-approval").last
            restored.get_by_role("button", name="Approve").click()
            expect(page.get_by_text("The refund is recorded.").last).to_be_visible(timeout=20000)
            state = ledger()
            assert [r["orderId"] for r in state["refunds"]] == ["O-1003", "O-1002"], state
            return f"the agent service was stopped and started while the approval waited; refunds after Approve: {[r['orderId'] for r in state['refunds']]}"

        def two_tabs():
            ask(page, "Refund order O-1001")
            first = page.locator(".sc-ai-approval").last.get_by_role("button", name="Approve")
            expect(first).to_be_visible(timeout=20000)
            other = context.new_page()
            other.goto(page.url)
            copy = other.locator(".desk-restored-approval").last.get_by_role("button", name="Approve")
            expect(copy).to_be_visible(timeout=20000)
            copy.click()
            expect(other.get_by_text("The refund is recorded.").last).to_be_visible(timeout=20000)
            first.click()
            expect(page.locator(".desk__error")).to_be_visible(timeout=20000)
            page.locator(".desk__error").scroll_into_view_if_needed()
            page.wait_for_timeout(300)
            page.screenshot(path=f"{OUT}/shot-2-second-answer-refused.png")
            state = ledger()
            other.close()
            assert [r["orderId"] for r in state["refunds"]] == ["O-1003", "O-1002", "O-1001"], state
            return f"second tab approved and was paid; the first tab's Approve was refused: \"{page.locator('.desk__error').inner_text()}\"; refunds {len(state['refunds'])}"

        def reload_mid_answer():
            page.goto(WEB)
            page.wait_for_url("**/c/*", timeout=20000)
            ask(page, "Explain the refund policy")
            expect(page.locator("button.desk-stop")).to_be_visible(timeout=20000)
            page.wait_for_timeout(1500)
            reload(page)
            expect(page.locator(".desk__notice")).to_be_visible(timeout=20000)
            text = page.locator("body").inner_text()
            words = len(text[text.rfind("Explain the refund policy"):].split()) - 4
            page.wait_for_timeout(1200)
            page.screenshot(path=f"{OUT}/shot-3-interrupted.png")
            last = wire()[-1]
            assert last["Completed"] is False and "RUN_FINISHED" not in last["Events"], last["Events"][-3:]
            again = len(page.locator("body").inner_text().split())
            page.wait_for_timeout(1500)
            assert len(page.locator("body").inner_text().split()) == again
            return f"reloaded 1.5 s into a long answer: about {words} words of 156 came back, with a notice; the run on the agent service ended early after {len(last['Events'])} events and did not continue"

        def default_buttons():
            stop("web")
            start("web", {"DESK_RESTORED_APPROVAL_BUTTONS": "false"})
            page.goto(WEB)
            page.wait_for_url("**/c/*", timeout=20000)
            ask(page, "Refund order O-1003")
            expect(page.locator(".sc-ai-approval").last.get_by_role("button", name="Approve")).to_be_visible(timeout=20000)
            reload(page)
            before, requests = ledger()["attempts"], len(wire())
            button = page.locator(".sc-ai-approval").last.get_by_role("button", name="Approve")
            expect(button).to_be_visible(timeout=20000)
            button.click()
            page.wait_for_timeout(2500)
            label = page.locator(".sc-ai-approval").last.inner_text().strip().splitlines()[-1]
            page.screenshot(path=f"{OUT}/shot-4-default-buttons.png")
            after = ledger()["attempts"]
            assert after == before and len(wire()) == requests, (before, after)
            return f"with the component's own buttons on a restored approval: the block now reads \"{label}\"; requests sent {len(wire()) - requests}; refund attempts {after - before}"

        step("a conversation has an address", address)
        step("reload", reload_keeps_it)
        step("shared state after a reload", state_comes_back)
        step("an approval that was waiting, after a reload", approval_survives_reload)
        step("an answered approval, after another reload", answered_stays_answered)
        step("the web app restarts", web_restart)
        step("the agent service restarts while an approval waits", agent_restart)
        step("two tabs answer the same approval", two_tabs)
        step("reload in the middle of an answer", reload_mid_answer)
        step("lab: the default buttons on a restored approval", default_buttons)
        browser.close()

    for name in list(processes):
        stop(name)
    with open(f"{OUT}/e2e.json", "w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=1)
    passed = sum(r["ok"] for r in results)
    print(f"{passed} of {len(results)} browser steps passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        for process in processes.values():
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except Exception:
                pass
