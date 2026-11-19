import base64
import json

import httpx
import pytest

import basics
from test_chat_api import client_with, completion


def test_ask_sends_system_and_user_and_reports_usage():
    seen = []
    a = basics.ask(client_with(lambda r: completion("Use json.load."), seen), "How do I read JSON?")
    body = json.loads(seen[0].content)
    assert [m["role"] for m in body["messages"]] == ["system", "user"] and body["max_tokens"] == 500
    assert (a.text, a.finish_reason, a.prompt_tokens, a.completion_tokens) == ("Use json.load.", "stop", 120, 30)


def test_conversation_resends_history_and_caps_turns():
    seen, n = [], iter(range(100))
    c = client_with(lambda r: completion(f"reply {next(n)}"), seen)
    conv = basics.Conversation(c, "Be brief.", max_turns=2)
    for q in ["q1", "q2", "q3"]:
        conv.send(q)
    sent = [m["content"] for m in json.loads(seen[1].content)["messages"]]
    assert sent == ["Be brief.", "q1", "reply 0", "q2"]
    last = [m["content"] for m in json.loads(seen[2].content)["messages"]]
    assert last == ["Be brief.", "q2", "reply 1", "q3"]  # q1 dropped, system kept
    assert len(conv.history) == 6


def test_image_part_from_file_uses_real_mime_type(tmp_path):
    png = tmp_path / "shot.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    part = basics.image_part(str(png), detail="low")
    url = part["image_url"]["url"]
    assert url.startswith("data:image/png;base64,") and base64.b64decode(url.split(",", 1)[1]).startswith(b"\x89PNG")
    assert part["image_url"]["detail"] == "low"
    with pytest.raises(ValueError):
        basics.image_part(str(tmp_path / "notes.pdf"))


def test_describe_image_sends_text_and_image_parts():
    seen = []
    a = basics.describe_image(client_with(lambda r: completion("A bar chart."), seen),
                              "https://example.com/chart.png", "What does this show?")
    content = json.loads(seen[0].content)["messages"][0]["content"]
    assert [p["type"] for p in content] == ["text", "image_url"] and a.text == "A bar chart."
