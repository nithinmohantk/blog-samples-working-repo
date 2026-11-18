import pytest

from claude_migrate.legacy import PromptFormatError, convert_body, parse_prompt, prefill_of


def test_system_text_before_the_first_human_turn():
    system, messages = parse_prompt("You are a terse assistant.\n\nHuman: Hi\n\nAssistant:")
    assert system == "You are a terse assistant."
    assert messages == [{"role": "user", "content": "Hi"}]


def test_multi_turn_and_prefill():
    prompt = "\n\nHuman: Name a colour.\n\nAssistant: Blue.\n\nHuman: Another, as JSON.\n\nAssistant: {\"colour\":"
    system, messages = parse_prompt(prompt)
    assert system is None
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[-1]["content"] == '{"colour":'


def test_consecutive_human_turns_are_merged():
    _, messages = parse_prompt("\n\nHuman: Part one.\n\nHuman: Part two.\n\nAssistant:")
    assert messages == [{"role": "user", "content": "Part one.\n\nPart two."}]


@pytest.mark.parametrize("prompt", [
    "Hello",                                        # no Human turn
    "\n\nHuman: Hi",                                # does not end with Assistant
    "\n\nAssistant: I start\n\nHuman: Hi\n\nAssistant:",  # starts with Assistant
    "\n\nHuman:\n\nAssistant:",                    # empty Human turn
])
def test_malformed_prompts_are_rejected(prompt):
    with pytest.raises(PromptFormatError):
        parse_prompt(prompt)


def test_convert_body_maps_parameters_and_drops_the_human_stop_sequence():
    old = {"prompt": "Be brief.\n\nHuman: Summarise the note.\n\nAssistant:", "max_tokens_to_sample": 300,
           "stop_sequences": ["\n\nHuman:", "</summary>"], "temperature": 0.2, "top_k": 250}
    assert convert_body(old) == {
        "anthropic_version": "bedrock-2023-05-31", "max_tokens": 300, "system": "Be brief.",
        "messages": [{"role": "user", "content": [{"type": "text", "text": "Summarise the note."}]}],
        "stop_sequences": ["</summary>"], "temperature": 0.2, "top_k": 250,
    }


def test_prefill_of():
    body = convert_body({"prompt": "\n\nHuman: JSON please\n\nAssistant: {", "max_tokens_to_sample": 50})
    assert prefill_of(body) == "{"
