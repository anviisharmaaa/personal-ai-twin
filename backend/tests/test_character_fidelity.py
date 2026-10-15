# ruff: noqa: E501, F811
"""Character fidelity: the creator's original description reaches the model on every reply, with authority.

These tests capture the real HTTP request that OllamaChatProvider would send to Ollama (httpx MockTransport) after the
full path: bearer token -> ownership -> consent -> twin/description/profile/memories/history -> prompt assembly ->
provider. They prove what the model is GIVEN. They do not (and cannot) prove how a real model behaves with it; that is
a live check (scripts/live_chat_smoke.py)."""
import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.chat import ChatError, ChatMessage, OllamaChatProvider, system_prompt
from app.config import get_settings
from app.providers import consent_version
from tests.conftest import auth
from tests.fake_supabase import FakeSupabase
from tests.test_chat import DESC, PROFILE, _reset, new_conversation, ollama_env, parse_sse, ready_user, send, use  # noqa: F401

PERSONA = ["authoritative", "mannerisms", "emotional reactions", "Do not recite", "do not drift into a generic assistant"]


class Capture:
    """A real OllamaChatProvider whose HTTP layer records each request body and answers with a tiny valid stream."""

    def __init__(self, prompt_tokens: int = 4000) -> None:
        self.bodies: list[dict[str, Any]] = []
        self.provider = OllamaChatProvider("http://localhost:11434/v1", "qwen-test:9b", max_output_tokens=64,
                                           first_token_timeout=5, total_timeout=30,
                                           transport=httpx.MockTransport(self._handle))
        self.prompt_tokens = prompt_tokens

    def _handle(self, req: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(req.content))
        chunk = {"choices": [{"delta": {"content": "Sure."}}]}
        end = {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": self.prompt_tokens, "completion_tokens": 2}}
        body = f"data: {json.dumps(chunk)}\n\ndata: {json.dumps(end)}\n\ndata: [DONE]\n\n".encode()
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    @property
    def system(self) -> str:
        return str(self.bodies[-1]["messages"][0]["content"])

    @property
    def roles(self) -> list[str]:
        return [m["role"] for m in self.bodies[-1]["messages"]]


def prep(client: TestClient, fake: FakeSupabase, *, profile: bool = True, user: str = "alice") -> tuple[dict[str, str], str, Capture]:
    h = ready_user(client, fake, user, profile=profile)
    cap = Capture()
    use(cap.provider)
    return h, new_conversation(client, h), cap


def test_the_original_description_is_in_the_request_sent_to_ollama(client: TestClient, fake: FakeSupabase, ollama_env: None) -> None:
    h, cid, cap = prep(client, fake)
    assert send(client, h, cid, "How was your day?").status_code == 200
    body = cap.bodies[0]
    assert body["stream"] is True and body["model"] == "qwen-test:9b"
    assert cap.roles == ["system", "user"]
    sysmsg = cap.system
    assert DESC in sysmsg                                                       # verbatim, the user's own words
    assert "<original_description> AUTHORITATIVE" in sysmsg
    assert sysmsg.index("<original_description>") < sysmsg.index("<character_profile>")   # description first
    assert "Warm with friends" in sysmsg and "SUPPLEMENTARY" in sysmsg           # the profile supplements it
    assert body["messages"][-1] == {"role": "user", "content": "How was your day?"}
    for phrase in PERSONA:
        assert phrase in sysmsg, phrase


def test_every_reply_in_a_conversation_carries_the_description_and_the_recent_history(client: TestClient, fake: FakeSupabase, ollama_env: None) -> None:
    h, cid, cap = prep(client, fake)
    for i, text in enumerate(["first", "second", "third"]):
        assert send(client, h, cid, text, f"key-fid-{i:05d}").status_code == 200
    assert len(cap.bodies) == 3
    assert all(DESC in b["messages"][0]["content"] for b in cap.bodies)
    last = [m["content"] for m in cap.bodies[2]["messages"][1:]]
    assert last == ["first", "Sure.", "second", "Sure.", "third"]               # recent history, in order


def test_a_long_description_is_included_in_full_not_truncated(client: TestClient, fake: FakeSupabase, ollama_env: None) -> None:
    h, cid, cap = prep(client, fake)
    long_desc = ("She is warm with friends. " * 280) + "FINAL-DETAIL: she always hums when she is nervous."
    assert len(long_desc) < 8000
    twin = fake.tables["twins"][0]
    twin["character_description"] = long_desc
    twin["character_version"] = 1
    send(client, h, cid, "hello")
    assert "FINAL-DETAIL: she always hums when she is nervous." in cap.system and long_desc in cap.system


def test_editing_the_description_changes_the_next_reply_and_flags_the_old_profile(client: TestClient, fake: FakeSupabase, ollama_env: None) -> None:
    h, cid, cap = prep(client, fake)
    send(client, h, cid, "hello", "key-fid-00001")
    new = DESC + " Since last month she has taken up night-time cycling and talks about it constantly."
    assert client.put("/api/v1/twin/character", json={"description": new, "base_version": 1}, headers=h).status_code == 200
    ev = parse_sse(send(client, h, cid, "what's new?", "key-fid-00002").text)
    assert "night-time cycling" in cap.system                                   # the edit reached the model at once
    assert "OUT OF DATE" in cap.system and "follow the original description" in cap.system
    assert ev[0][1]["profile_state"] == "outdated" and ev[0][1]["profile_outdated"] is True


def test_chat_works_from_the_description_alone_when_there_is_no_profile(client: TestClient, fake: FakeSupabase, ollama_env: None) -> None:
    h, cid, cap = prep(client, fake, profile=False)
    ev = parse_sse(send(client, h, cid, "hi").text)
    assert ev[-1][0] == "done" and ev[0][1]["profile_state"] == "missing"
    assert DESC in cap.system
    assert "NOT AVAILABLE" in cap.system and "do not invent traits" in cap.system
    assert "Warm with friends" not in cap.system                                 # nothing was made up to fill the gap
    assert client.get("/api/v1/chat/status", headers=h).json()["profile_state"] == "missing"


def test_without_a_description_there_is_no_character_and_nothing_reaches_the_model(client: TestClient, fake: FakeSupabase, ollama_env: None) -> None:
    h = auth("dana")
    client.put("/api/v1/twin", json={"name": "Meera"}, headers=h)
    client.post("/api/v1/consents/ai-processing", json={"version": consent_version(get_settings())}, headers=h)
    cap = Capture()
    use(cap.provider)
    cid = new_conversation(client, h)
    r = send(client, h, cid, "hi")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_character"
    assert cap.bodies == [] and fake.tables["messages"] == []


def test_each_user_gets_only_their_own_character(client: TestClient, fake: FakeSupabase, ollama_env: None) -> None:
    ha, cida, capa = prep(client, fake, user="alice")
    hb = ready_user(client, fake, "bob")
    fake.tables["twins"][1]["character_description"] = "Bob's character is a gruff retired sailor who speaks in short sentences."
    capb = Capture()
    use(capb.provider)
    cidb = new_conversation(client, hb)
    send(client, hb, cidb, "ahoy")
    assert "gruff retired sailor" in capb.system and DESC not in capb.system
    use(capa.provider)
    send(client, ha, cida, "hello")
    assert DESC in capa.system and "gruff retired sailor" not in capa.system


def test_approved_memories_join_the_description_but_unapproved_ones_do_not_and_the_description_is_never_changed(client: TestClient, fake: FakeSupabase, ollama_env: None) -> None:
    h, cid, cap = prep(client, fake)
    twin = fake.tables["twins"][0]
    base = {"owner_id": "alice", "twin_id": twin["id"], "category": "preference", "scope": "", "supporting": [], "evidence_type": "explicit_statement", "fingerprint": "f"}
    fake.tables["memories"].append({"id": "m1", "statement": "She takes her chai without sugar", "status": "active", **base})
    fake.tables["memory_candidates"].append({"id": "c1", "statement": "She secretly dislikes chai", "status": "pending", **base})
    before = twin["character_description"]
    send(client, h, cid, "any chai?")
    assert DESC in cap.system and "without sugar" in cap.system and "secretly dislikes" not in cap.system
    assert cap.system.index("<original_description>") < cap.system.index("<approved_memories>")
    assert twin["character_description"] == before                               # learning never rewrites it


def test_a_prompt_that_the_server_truncated_is_reported_not_passed_off_as_a_faithful_reply(client: TestClient, fake: FakeSupabase, ollama_env: None) -> None:
    h = ready_user(client, fake)
    cap = Capture(prompt_tokens=40)                  # far fewer tokens than the prompt has: the context window cut it
    use(cap.provider)
    cid = new_conversation(client, h)
    ev = parse_sse(send(client, h, cid, "hello").text)
    assert ev[-1][0] == "error" and ev[-1][1]["code"] == "context_too_small"
    a = [m for m in fake.tables["messages"] if m["role"] == "assistant"][0]
    assert a["status"] == "failed" and a["failure_code"] == "context_too_small"


def test_system_prompt_unit_shape() -> None:
    text = system_prompt("Meera", PROFILE, DESC, [])
    order = [text.index(t) for t in ("Source of truth", "<original_description>", "<character_profile>")]
    assert order == sorted(order)
    assert "No structured interpretation" not in text
    none = system_prompt("Meera", None, DESC, [])
    assert "NOT AVAILABLE" in none and DESC in none
    empty_profile = system_prompt("Meera", {"summary": ""}, DESC, [])
    assert "NOT AVAILABLE" in empty_profile
    # the provider receives exactly the messages built from it
    assert ChatMessage("system", text).role == "system"


@pytest.mark.anyio
async def test_a_guarded_stream_still_yields_its_text_before_the_error() -> None:
    cap = Capture(prompt_tokens=10)
    got: list[str] = []
    with pytest.raises(ChatError) as e:
        async for kind, val in cap.provider.stream([ChatMessage("system", "x" * 3000), ChatMessage("user", "hi")]):
            if kind == "delta":
                got.append(val)
    assert got == ["Sure."] and e.value.code == "context_too_small"
