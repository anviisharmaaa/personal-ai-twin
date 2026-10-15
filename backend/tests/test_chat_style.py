"""Natural, short, in-character replies and fast local chat. MOCKED: the real OllamaChatProvider over
httpx.MockTransport, so these prove what Madhuora SENDS to Ollama and how it handles the answer; the speed itself is
measured live (scripts/chat_latency_bench.py), never here."""
# ruff: noqa: F811
from __future__ import annotations

import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from app.chat import OllamaChatProvider, build_chat_provider, system_prompt
from app.config import Settings
from tests.fake_supabase import FakeSupabase
from tests.test_character_fidelity import DESC, PROFILE, Capture, prep
from tests.test_chat import _reset, ollama_env, parse_sse, send  # noqa: F401  (fixtures re-exported below)  # noqa: F401


def native(**kw: object) -> OllamaChatProvider:
    return OllamaChatProvider("http://localhost:11434/v1", "qwen3.5:9b", max_output_tokens=128, first_token_timeout=5,
                              total_timeout=30, transport=httpx.MockTransport(lambda r: httpx.Response(200)), **kw)  # type: ignore[arg-type]


# ---- the prompt ----------------------------------------------------------------------------------------------------

def test_prompt_asks_for_varied_conversational_lengths_not_one_formula() -> None:
    text = system_prompt("Meera", PROFILE, DESC, [])
    assert "Length follows the moment" in text
    for step in ("a single word", "one short sentence", "a line or two", "a few conversational lines"):
        assert step in text, step
    assert "longer only when the user asks for detail or a story" in text      # not a rigid limit
    assert "Do not settle into one shape" in text
    assert "Never pad" in text and "Do not repeat back what the user just said" in text
    assert "Ask a question back only when it comes naturally" in text


def test_prompt_discourages_repeating_signature_phrases_without_naming_any() -> None:
    text = system_prompt("Meera", PROFILE, DESC, [])
    assert "A voice is more than its catchphrases" in text and "sparingly and unevenly" in text
    assert "Do not open or close with the same word, greeting, laugh or emoji" in text
    assert "read your earlier replies in this conversation" in text
    # The rules are written for every character: no one character's slang is baked into them.
    for borrowed in ("yaar", "haha", "chal", "lowercase", "beta", "dude", "bro"):
        assert borrowed not in text.lower(), borrowed


def test_prompt_puts_feelings_first_and_makes_teasing_context_sensitive() -> None:
    text = system_prompt("Meera", PROFILE, DESC, [])
    assert "Feelings come first" in text and "in the way this character cares for people (as described)" in text
    assert "rush to fix it or hand out advice unless they ask" in text
    assert "do not tease or joke unless the description says this character does so" in text
    assert "A teasing character teases when the mood is light and gentles when it is not" in text
    assert "drop any joking, respond with real care" in text                    # the distress safeguard remains


def test_prompt_forbids_inventing_a_shared_past_or_real_world_promises() -> None:
    text = system_prompt("Meera", PROFILE, DESC, [])
    assert "Never invent a shared past" in text
    for banned in ("events you did together", "earlier conversations", "promises", "personal history"):
        assert banned in text, banned
    assert "not in the description, the approved memories or this conversation" in text
    assert "say so in your own way instead of pretending to remember" in text
    assert "Do not promise to do things in the real world" in text


def test_prompt_answers_real_questions_and_stays_honest_about_being_an_ai() -> None:
    text = system_prompt("Meera", PROFILE, DESC, [])
    assert "Real questions get real answers" in text and "A quirk is a style, not a reason to dodge" in text
    assert "Put the most useful part first" in text                            # survives the output ceiling better
    assert "Staying in character is not deception" in text
    assert "an AI, a bot or a real person, or how Madhuora works" in text
    assert "you are an AI voicing this character, not a real person" in text
    assert "Never claim to be human" in text and "do not bring it up or add a disclaimer" in text
    for phrase in ("As an AI", "I'm just a language model", "How can I assist you today?", "I'm here to help"):
        assert phrase in text                                                  # only inside the "never say" rule
    assert 'Never say things like "As an AI"' in text


def test_the_character_stays_authoritative_and_the_style_reminder_comes_last() -> None:
    text = system_prompt("Meera", PROFILE, DESC, [{"category": "preference", "statement": "likes chai", "scope": ""}])
    assert "<original_description> AUTHORITATIVE" in text and DESC in text
    assert text.index("<original_description>") < text.index("<character_profile>") < text.index("<approved_memories>")
    assert text.rstrip().endswith("No assistant phrasing.")
    assert "Feelings first when the user is hurting" in text.rsplit("Reminder:", 1)[1]
    assert "mannerisms" in text and "emotional reactions" in text           # personality is still the source of style
    assert "Each character sounds like themselves" in text                  # no universal friendly personality


def test_two_characters_get_their_own_style_source_and_the_same_neutral_rules() -> None:
    blunt = "Bram is a blunt retired carpenter who speaks in few words and never uses emojis."
    gushy = "Lila is an effusive florist who loves exclamation marks and pet names."
    a, b = system_prompt("Bram", None, blunt, []), system_prompt("Lila", None, gushy, [])
    assert blunt in a and gushy not in a and gushy in b and blunt not in b
    assert a.split("The character's creator calls them")[0] == b.split("The character's creator calls them")[0]


def test_the_fixed_rules_stay_within_a_size_budget() -> None:
    """The rules are re-read by the model on every uncached message, so growth costs first-token time."""
    from app.chat import STYLE_REMINDER, SYSTEM_RULES
    assert len(SYSTEM_RULES) < 6500 and len(STYLE_REMINDER) < 400


# ---- the request that really goes to Ollama --------------------------------------------------------------------------

def test_chat_request_uses_the_native_api_with_thinking_off_and_the_chat_output_limit(
        client: TestClient, fake: FakeSupabase, ollama_env: None) -> None:
    h, cid, cap = prep(client, fake)
    assert send(client, h, cid, "heyy").status_code == 200
    body = cap.bodies[-1]
    assert body["think"] is False                                           # the documented native switch
    assert body["stream"] is True and body["options"]["num_predict"] == 64  # the provider's own configured ceiling
    assert "max_tokens" not in body and "reasoning_effort" not in body      # the /v1 spellings are not mixed in
    assert body["keep_alive"] == "30m"
    assert body["messages"][0]["role"] == "system" and DESC in body["messages"][0]["content"]


def test_native_endpoint_is_derived_from_the_configured_v1_url() -> None:
    assert native()._url == "http://localhost:11434/api/chat"
    p = OllamaChatProvider("http://localhost:11434", "m", max_output_tokens=16, first_token_timeout=5, total_timeout=30)
    assert p._url == "http://localhost:11434/api/chat"
    s = native().settings_summary()
    assert s["think"] is False and s["num_predict"] == 128 and s["endpoint"] == "native /api/chat"


def test_num_ctx_is_sent_only_when_configured() -> None:
    assert "num_ctx" not in native()._payload([])["options"]
    assert native(num_ctx=8192)._payload([])["options"]["num_ctx"] == 8192
    assert native(think=True)._payload([])["think"] is True                 # an explicit opt-in, never the default


# ---- limits: chat is separate from analysis and learning -------------------------------------------------------

def test_chat_limit_is_configurable_and_other_features_keep_their_own_limits() -> None:
    s = Settings(_env_file=None)                                           # type: ignore[call-arg]
    assert s.chat_max_output_tokens == 128 and s.chat_think is False
    assert s.analysis_max_output_tokens == 3000 and s.ollama_max_output_tokens == 4096
    assert s.learning_max_output_tokens == 1536                             # untouched by the chat change
    custom = Settings(_env_file=None, chat_max_output_tokens=200, ai_provider="ollama", ollama_character_model="m")  # type: ignore[call-arg]
    chat = build_chat_provider(custom)
    assert isinstance(chat, OllamaChatProvider) and chat.settings_summary()["num_predict"] == 200
    assert custom.ollama_max_output_tokens == 4096                          # analysis limit did not move


def test_analysis_still_uses_the_v1_endpoint_and_its_own_token_limit() -> None:
    from app.providers import OllamaAnalyzer
    a = OllamaAnalyzer("http://localhost:11434/v1", "m", 60.0, 4096, allowed=True)
    assert a._max_out == 4096 and a.PROVIDER == "ollama"


# ---- behaviour of the stream and the saved result ---------------------------------------------------------------

def test_a_reply_that_hits_the_ceiling_is_saved_as_incomplete_not_complete(
        client: TestClient, fake: FakeSupabase, ollama_env: None) -> None:
    from tests.test_chat import new_conversation, ready_user, use
    h = ready_user(client, fake)
    cap = Capture(reason="length")
    use(cap.provider)
    cid = new_conversation(client, h)
    ev = parse_sse(send(client, h, cid, "tell me everything").text)
    assert ev[-1][0] == "error" and ev[-1][1]["code"] == "truncated" and ev[-1][1]["partial_saved"] is True
    a = [m for m in fake.tables["messages"] if m["role"] == "assistant"][0]
    assert a["status"] == "incomplete" and a["content"] == "Sure."


def test_timing_diagnostics_are_logged_without_message_content(
        client: TestClient, fake: FakeSupabase, ollama_env: None, caplog: pytest.LogCaptureFixture) -> None:
    h, cid, cap = prep(client, fake)
    with caplog.at_level(logging.INFO, logger="madhuora.chat"):
        send(client, h, cid, "my secret plan is purple elephants")
    line = next(r.getMessage() for r in caplog.records if r.getMessage().startswith("chat_timing"))
    for field in ("first_token_ms=", "total_ms=", "output_tokens=2", "prompt_tokens=", "status=complete",
                  "num_predict"):
        assert field in line, field
    assert "think" in line
    assert "purple elephants" not in caplog.text and "Sure." not in caplog.text and DESC not in caplog.text
