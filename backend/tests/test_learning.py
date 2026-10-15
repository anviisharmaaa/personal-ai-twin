# ruff: noqa: E501
"""Conversation-driven learning. MOCKED: the extractor is a scripted fake and FakeSupabase approximates RLS. None of
this is evidence about how real Ollama extracts memories (see docs/LIVE_VERIFICATION.md)."""
import json
import logging
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.chat import ChatError, model_gate
from app.conversation_routes import _streaming, get_chat_provider
from app.learning import OllamaExtractor, fingerprint, overlap, render_conversation, validate_candidates
from app.learning_routes import DISCLOSURE_VERSION, _reviewing, get_extractor
from app.main import app
from tests.conftest import auth
from tests.fake_supabase import FakeSupabase
from tests.test_chat import DESC, PROFILE, ScriptedChat, new_conversation, ready_user, send, use


class ScriptedExtractor:
    configured = True

    def __init__(self, raw: object = None, *, fail: ChatError | None = None, hook: Any = None) -> None:
        self.raw, self.fail, self.hook, self.calls = raw if raw is not None else [], fail, hook, []

    async def extract(self, conversation: str) -> object:
        self.calls.append(conversation)
        if self.hook:
            self.hook()
        if self.fail:
            raise self.fail
        return self.raw


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    for fx in (_streaming, _reviewing):
        fx.clear()
    model_gate.reset()
    yield
    for fx in (_streaming, _reviewing):
        fx.clear()
    model_gate.reset()
    app.dependency_overrides.pop(get_extractor, None)
    app.dependency_overrides.pop(get_chat_provider, None)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_CHARACTER_MODEL", "qwen-test:9b")
    get_settings.cache_clear()


def extractor(x: object) -> None:
    app.dependency_overrides[get_extractor] = lambda: x


def cand(statement: str, quote: str, message: str = "m1", category: str = "preference",
         evidence: str = "explicit_statement") -> dict[str, Any]:
    return {"statement": statement, "category": category, "scope": "", "evidence_type": evidence,
            "quotes": [{"message": message, "quote": quote}]}


def enable_learning(client: TestClient, h: dict[str, str]) -> None:
    r = client.put("/api/v1/learning/preference", json={"enabled": True, "disclosure_version": DISCLOSURE_VERSION}, headers=h)
    assert r.status_code == 200 and r.json()["enabled"] is True


def chat_with(client: TestClient, h: dict[str, str], *texts: str) -> str:
    cid = new_conversation(client, h)
    use(ScriptedChat(["Noted."]))
    for i, t in enumerate(texts):
        assert send(client, h, cid, t, f"key-{i:08d}").status_code == 200
    return cid


def review(client: TestClient, h: dict[str, str], cid: str) -> httpx.Response:
    return client.post(f"/api/v1/conversations/{cid}/learning/review", headers=h)


def learning(client: TestClient, h: dict[str, str], cid: str) -> dict[str, Any]:
    return dict(client.get(f"/api/v1/conversations/{cid}/learning", headers=h).json())


TEA = "I really like masala chai in the mornings."
LOUD = "I get tired at loud parties and leave early."


def pending_chai(client: TestClient, h: dict[str, str]) -> tuple[str, dict[str, Any]]:
    cid = chat_with(client, h, TEA, "Thanks for listening.")
    extractor(ScriptedExtractor([cand("She likes masala chai in the mornings", "like masala chai in the mornings")]))
    assert review(client, h, cid).status_code == 202
    c = learning(client, h, cid)["candidates"][0]
    return cid, c


# ---- pure validation ---------------------------------------------------------------------------------------------------

def msgs(*pairs: tuple[str, str]) -> dict[str, dict[str, Any]]:
    return {f"m{i}": {"id": f"id{i}", "role": "user", "content": c} for i, (_, c) in enumerate(pairs, 1)}


def test_validation_accepts_only_verbatim_user_quotes_with_provenance() -> None:
    um = {"m1": {"id": "u1", "role": "user", "content": TEA}}
    ok, rej = validate_candidates([cand("She likes masala chai", "really like masala chai")], um, set(), 8)
    assert len(ok) == 1 and ok[0]["supporting"] == [{"message_id": "u1", "quote": "really like masala chai"}]
    assert ok[0]["fingerprint"] == fingerprint("She likes masala chai") and not rej.counts
    cases = {
        "invented quote": cand("She likes tea", "I adore green tea very much", "m1"),
        "assistant message": cand("She likes tea", "masala chai", "m2"),      # m2 is an assistant turn: not citable
        "ellipsis stitched": cand("She likes chai", "really like ... mornings"),
        "too short": cand("She likes chai", "chai"),
        "statement unsupported": cand("He plays cricket professionally", "really like masala chai"),
        "bad category": {**cand("She likes chai", "really like masala chai"), "category": "secret"},
        "no quotes": {**cand("She likes chai", "x"), "quotes": []},
    }
    for name, c in cases.items():
        out, r = validate_candidates([c], um, set(), 8)
        assert out == [] and r.counts, name


def test_validation_drops_hypotheticals_moods_unsupported_patterns_and_sensitive_guesses() -> None:
    um = {"m1": {"id": "u1", "role": "user", "content": "Imagine I hate all my friends and love spicy food."},
          "m2": {"id": "u2", "role": "user", "content": "Today I'm feeling very angry at everyone around me."},
          "m3": {"id": "u3", "role": "user", "content": "I always check the weather before leaving home."},
          "m4": {"id": "u4", "role": "user", "content": "Please remember that I never eat mushrooms at all."}}
    rows = [
        cand("She loves spicy food", "love spicy food"),
        cand("She is angry at everyone", "feeling very angry at everyone", "m2"),
        cand("She checks the weather before leaving", "check the weather before leaving home", "m3", "trait", "repeated_pattern"),
        cand("She is religious", "check the weather", "m3"),
        cand("She never eats mushrooms", "never eat mushrooms at all", "m4", "boundary", "memory_request"),
    ]
    out, rej = validate_candidates(rows, um, set(), 8)
    assert [o["statement"] for o in out] == ["She never eats mushrooms"]
    assert set(rej.counts) >= {"hypothetical_or_roleplay", "passing_mood", "pattern_needs_two_messages"}
    # a memory request must really be one
    out, rej = validate_candidates([cand("She likes weather checks", "check the weather before leaving home", "m3", evidence="memory_request")], um, set(), 8)
    assert out == [] and "no_memory_request" in rej.counts


def test_validation_dedupes_respects_rejected_fingerprints_and_the_limit() -> None:
    um = {"m1": {"id": "u1", "role": "user", "content": "I like chai. I like quiet mornings. I like long walks. I like old films."}}
    rows = [cand("She likes chai", "I like chai"), cand("Chai is liked by her", "I like chai"),
            cand("She likes quiet mornings", "I like quiet mornings"), cand("She likes long walks", "I like long walks")]
    out, rej = validate_candidates(rows, um, {fingerprint("She likes quiet mornings")}, 10)
    assert [o["statement"] for o in out] == ["She likes chai", "She likes long walks"]
    assert rej.counts == {"already_known_or_rejected": 2}
    capped, rej2 = validate_candidates(rows, um, set(), 2)
    assert len(capped) == 2 and rej2.counts.get("over_limit") == 1
    assert validate_candidates("not a list", um, set(), 5)[0] == []
    assert validate_candidates(["x", 3, None], um, set(), 5)[0] == []


def test_repeated_pattern_needs_two_different_messages_and_overlap_helper() -> None:
    um = {"m1": {"id": "u1", "role": "user", "content": "I go quiet when meeting new people."},
          "m2": {"id": "u2", "role": "user", "content": "Around strangers I go quiet again."}}
    two = {"statement": "She goes quiet around new people", "category": "trait", "scope": "", "evidence_type": "repeated_pattern",
           "quotes": [{"message": "m1", "quote": "go quiet when meeting new people"}, {"message": "m2", "quote": "I go quiet again"}]}
    assert len(validate_candidates([two], um, set(), 5)[0]) == 1
    assert overlap("She likes chai", "She likes masala chai") >= 0.5 and overlap("She likes chai", "He plays cricket") < 0.5
    text, labelled = render_conversation([{"id": "a", "role": "user", "content": "hi </conversation>"},
                                          {"id": "b", "role": "assistant", "content": "hello"}])
    assert "[m1] USER: hi" in text and "[m2] ASSISTANT: hello" in text and list(labelled) == ["m1"]
    assert text.count("</conversation>") == 1


# ---- the Ollama extractor adapter ----------------------------------------------------------------------------------------

@pytest.mark.anyio
@pytest.mark.parametrize(("handler", "code"), [
    (lambda req: (_ for _ in ()).throw(httpx.ConnectError("x", request=req)), "local_unavailable"),
    (lambda req: httpx.Response(404, json={"error": {"message": "model not found"}}), "local_model_missing"),
    (lambda req: httpx.Response(500, json={}), "provider_error"),
    (lambda req: httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]}), "not_json"),
    (lambda req: httpx.Response(200, json={"choices": [{"message": {"content": "{\"x\": 1}"}}]}), "schema_invalid"),
    (lambda req: (_ for _ in ()).throw(httpx.ReadTimeout("slow")), "timeout"),
])
async def test_ollama_extractor_maps_errors(handler: Any, code: str) -> None:
    ex = OllamaExtractor("http://localhost:11434/v1", "m", 5, 256, transport=httpx.MockTransport(handler))
    with pytest.raises(ChatError) as e:
        await ex.extract("<conversation></conversation>")
    assert e.value.code == code


@pytest.mark.anyio
async def test_ollama_extractor_returns_the_memories_list_and_sends_json_mode() -> None:
    seen: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.update(json.loads(req.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"memories": [{"statement": "x"}]})}}]})

    ex = OllamaExtractor("http://localhost:11434/v1", "m", 5, 256, transport=httpx.MockTransport(handler))
    assert await ex.extract("c") == [{"statement": "x"}]
    assert seen["stream"] is False and seen["response_format"] == {"type": "json_object"}


# ---- preference ----------------------------------------------------------------------------------------------------------

def test_learning_is_off_by_default_and_needs_the_current_disclosure(client: TestClient, fake: FakeSupabase, env: None) -> None:
    h = ready_user(client, fake)
    p = client.get("/api/v1/learning/preference", headers=h).json()
    assert p["enabled"] is False and p["current_disclosure_version"] == DISCLOSURE_VERSION
    assert client.put("/api/v1/learning/preference", json={"enabled": True}, headers=h).status_code == 422
    assert client.put("/api/v1/learning/preference", json={"enabled": True, "disclosure_version": "old"}, headers=h).status_code == 422
    enable_learning(client, h)
    assert client.get("/api/v1/learning/preference", headers=h).json()["enabled"] is True
    off = client.put("/api/v1/learning/preference", json={"enabled": False}, headers=h).json()
    assert off["enabled"] is False and off["disabled_at"]


def test_review_is_refused_while_learning_is_off(client: TestClient, fake: FakeSupabase, env: None) -> None:
    h = ready_user(client, fake)
    cid = chat_with(client, h, TEA)
    extractor(ScriptedExtractor())
    r = review(client, h, cid)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "learning_disabled"
    assert fake.tables["memory_candidates"] == []


def test_turning_learning_off_stops_reviews_but_keeps_existing_memories(client: TestClient, fake: FakeSupabase, env: None) -> None:
    h = ready_user(client, fake)
    enable_learning(client, h)
    cid, c = pending_chai(client, h)
    assert client.post(f"/api/v1/memory/candidates/{c['id']}/approve", json={}, headers=h).status_code == 201
    client.put("/api/v1/learning/preference", json={"enabled": False}, headers=h)
    assert review(client, h, cid).status_code == 403
    assert len(client.get("/api/v1/memories", headers=h).json()["memories"]) == 1


# ---- review job ----------------------------------------------------------------------------------------------------------

def test_review_creates_pending_candidates_with_provenance_and_no_memory(client: TestClient, fake: FakeSupabase, env: None) -> None:
    h = ready_user(client, fake)
    enable_learning(client, h)
    cid, c = pending_chai(client, h)
    assert c["status"] == "pending" and c["supporting"][0]["quote"] == "like masala chai in the mornings"
    assert c["supporting"][0]["message_id"] in {m["id"] for m in fake.tables["messages"] if m["role"] == "user"}
    assert client.get("/api/v1/memories", headers=h).json()["memories"] == []        # nothing is remembered yet
    st = learning(client, h, cid)
    assert st["state"] == "idle" and st["failure_code"] is None and st["reviewed_at"]
    assert model_gate.busy is False and _reviewing == set()


def test_extractor_sees_the_conversation_labelled_and_never_the_profile(client: TestClient, fake: FakeSupabase, env: None) -> None:
    h = ready_user(client, fake)
    enable_learning(client, h)
    cid = chat_with(client, h, TEA)
    ex = ScriptedExtractor()
    extractor(ex)
    review(client, h, cid)
    assert "[m1] USER: " + TEA in ex.calls[0] and "[m2] ASSISTANT: Noted." in ex.calls[0]
    assert DESC not in ex.calls[0] and PROFILE["summary"] not in ex.calls[0]


@pytest.mark.parametrize(("provider", "code"), [("mock", "learning_unavailable_in_sample_mode"), ("nvidia", "learning_provider_unsupported"), ("openai", "learning_provider_unsupported")])
def test_learning_only_runs_on_the_local_model(client: TestClient, fake: FakeSupabase, env: None, monkeypatch: pytest.MonkeyPatch, provider: str, code: str) -> None:
    h = ready_user(client, fake)
    enable_learning(client, h)
    cid = chat_with(client, h, TEA)
    monkeypatch.setenv("AI_PROVIDER", provider)
    monkeypatch.setenv("NVIDIA_API_KEY", "k")
    monkeypatch.setenv("NVIDIA_CHARACTER_MODEL", "m")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("OPENAI_CHARACTER_MODEL", "m")
    from app.config import get_settings
    get_settings.cache_clear()
    # consent for the new provider is needed first, so give it
    from app.providers import consent_version
    client.post("/api/v1/consents/ai-processing", json={"version": consent_version(get_settings())}, headers=h)
    r = review(client, h, cid)
    assert r.status_code == 503 and r.json()["detail"]["code"] == code
    assert fake.tables["memory_candidates"] == []


def test_a_failed_extraction_is_recorded_and_does_not_break_chat(client: TestClient, fake: FakeSupabase, env: None) -> None:
    h = ready_user(client, fake)
    enable_learning(client, h)
    cid = chat_with(client, h, TEA)
    extractor(ScriptedExtractor(fail=ChatError("not_json", "bad", 502)))
    assert review(client, h, cid).status_code == 202
    st = learning(client, h, cid)
    assert st["failure_code"] == "not_json" and st["candidates"] == [] and st["state"] == "idle"
    assert model_gate.busy is False
    use(ScriptedChat(["still working"]))
    r = send(client, h, cid, "Are you still there?", "key-99999999")
    assert r.status_code == 200 and '"status":"complete"' in r.text
    extractor(ScriptedExtractor([]))                                     # a later success clears the failure code
    review(client, h, cid)
    assert learning(client, h, cid)["failure_code"] is None


def test_withdrawing_consent_or_learning_during_extraction_writes_nothing(client: TestClient, fake: FakeSupabase, env: None) -> None:
    h = ready_user(client, fake)
    enable_learning(client, h)
    cid = chat_with(client, h, TEA)

    def switch_off() -> None:
        client.put("/api/v1/learning/preference", json={"enabled": False}, headers=h)

    extractor(ScriptedExtractor([cand("She likes masala chai", "like masala chai")], hook=switch_off))
    review(client, h, cid)
    assert fake.tables["memory_candidates"] == [] and model_gate.busy is False

    enable_learning(client, h)
    consent = [c for c in fake.tables["consents"] if c["user_id"] == "alice"]

    def withdraw() -> None:
        for c in consent:
            c["withdrawn_at"] = "2026-10-15T01:00:00+00:00"

    extractor(ScriptedExtractor([cand("She likes masala chai", "like masala chai")], hook=withdraw))
    review(client, h, cid)
    assert fake.tables["memory_candidates"] == []


def test_review_guards_consent_empty_busy_running_and_rate(client: TestClient, fake: FakeSupabase, env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    h = ready_user(client, fake)
    enable_learning(client, h)
    extractor(ScriptedExtractor())
    empty = new_conversation(client, h)
    assert review(client, h, empty).json()["detail"]["code"] == "nothing_to_review"
    cid = chat_with(client, h, TEA)
    assert model_gate.try_acquire()
    r = review(client, h, cid)
    assert r.status_code == 429 and r.json()["detail"]["code"] == "model_busy"
    model_gate.release()
    _reviewing.add(cid)
    assert review(client, h, cid).json()["detail"]["code"] == "in_progress"
    assert learning(client, h, cid)["state"] == "running"
    _reviewing.clear()
    monkeypatch.setenv("LEARNING_REVIEWS_PER_HOUR", "1")
    from app.config import get_settings
    get_settings.cache_clear()
    assert review(client, h, cid).status_code == 202
    assert review(client, h, cid).json()["detail"]["code"] == "rate_limited"
    for c in fake.tables["consents"]:
        c["withdrawn_at"] = "2026-10-15T01:00:00+00:00"
    monkeypatch.setenv("LEARNING_REVIEWS_PER_HOUR", "50")
    get_settings.cache_clear()
    assert review(client, h, cid).json()["detail"]["code"] == "consent_required"


def test_a_restart_never_leaves_a_review_stuck_running(client: TestClient, fake: FakeSupabase, env: None) -> None:
    h = ready_user(client, fake)
    cid = chat_with(client, h, TEA)
    assert learning(client, h, cid)["state"] == "idle"          # state lives in the process; nothing persisted to get stuck


def test_no_message_text_reaches_the_logs_during_review(client: TestClient, fake: FakeSupabase, env: None, caplog: pytest.LogCaptureFixture) -> None:
    h = ready_user(client, fake)
    enable_learning(client, h)
    cid = chat_with(client, h, "my very private confession about chai")
    extractor(ScriptedExtractor([cand("She confessed about chai", "private confession about chai")]))
    with caplog.at_level(logging.DEBUG):
        review(client, h, cid)
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "learning_done" in logged and "confession" not in logged and "chai" not in logged


# ---- approve / edit / reject / forget ----------------------------------------------------------------------------------

def test_nothing_is_remembered_until_approved_and_approval_keeps_the_quote(client: TestClient, fake: FakeSupabase, env: None) -> None:
    h = ready_user(client, fake)
    enable_learning(client, h)
    _, c = pending_chai(client, h)
    r = client.post(f"/api/v1/memory/candidates/{c['id']}/approve", json={}, headers=h)
    assert r.status_code == 201
    m = r.json()["memory"]
    assert m["status"] == "active" and m["edited"] is False and m["supporting"][0]["quote"].startswith("like masala")
    assert client.get("/api/v1/memory/candidates", headers=h).json()["candidates"] == []
    assert client.post(f"/api/v1/memory/candidates/{c['id']}/approve", json={}, headers=h).json()["detail"]["code"] == "not_pending"


def test_edit_before_approving_and_edit_later(client: TestClient, fake: FakeSupabase, env: None) -> None:
    h = ready_user(client, fake)
    enable_learning(client, h)
    _, c = pending_chai(client, h)
    m = client.post(f"/api/v1/memory/candidates/{c['id']}/approve", json={"statement": "She enjoys masala chai at breakfast"}, headers=h).json()["memory"]
    assert m["edited"] is True and m["statement"] == "She enjoys masala chai at breakfast"
    p = client.patch(f"/api/v1/memories/{m['id']}", json={"pinned": True, "scope": "mornings"}, headers=h).json()["memory"]
    assert p["pinned"] is True and p["scope"] == "mornings"
    q = client.patch(f"/api/v1/memories/{m['id']}", json={"statement": "She enjoys strong masala chai"}, headers=h).json()["memory"]
    assert q["statement"] == "She enjoys strong masala chai" and q["edited"] is True


def test_a_rejected_idea_does_not_come_back(client: TestClient, fake: FakeSupabase, env: None) -> None:
    h = ready_user(client, fake)
    enable_learning(client, h)
    cid, c = pending_chai(client, h)
    assert client.post(f"/api/v1/memory/candidates/{c['id']}/reject", json={"reason": "wrong"}, headers=h).status_code == 200
    row = [x for x in fake.tables["memory_candidates"] if x["id"] == c["id"]][0]
    assert row["status"] == "rejected" and row["statement"] == "" and row["supporting"] == [] and row["fingerprint"]
    extractor(ScriptedExtractor([cand("She likes masala chai in the mornings", "like masala chai in the mornings")]))
    review(client, h, cid)
    assert learning(client, h, cid)["candidates"] == []


def test_duplicates_and_conflicts_are_asked_about_not_decided(client: TestClient, fake: FakeSupabase, env: None) -> None:
    h = ready_user(client, fake)
    enable_learning(client, h)
    cid, c = pending_chai(client, h)
    first = client.post(f"/api/v1/memory/candidates/{c['id']}/approve", json={}, headers=h).json()["memory"]
    extractor(ScriptedExtractor([cand("She now prefers masala chai in the evenings", "like masala chai in the mornings")]))
    review(client, h, cid)
    c2 = learning(client, h, cid)["candidates"][0]
    r = client.post(f"/api/v1/memory/candidates/{c2['id']}/approve", json={}, headers=h)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "conflict"
    assert r.json()["detail"]["conflicting"] == [{"id": first["id"], "statement": first["statement"]}]
    assert len(client.get("/api/v1/memories", headers=h).json()["memories"]) == 1          # nothing was chosen silently
    dup = client.post(f"/api/v1/memory/candidates/{c2['id']}/approve", json={"statement": first["statement"]}, headers=h)
    assert dup.status_code == 409 and dup.json()["detail"]["code"] == "duplicate"
    ok = client.post(f"/api/v1/memory/candidates/{c2['id']}/approve", json={"resolution": "replace"}, headers=h)
    assert ok.status_code == 201
    active = client.get("/api/v1/memories", headers=h).json()["memories"]
    assert [m["statement"] for m in active] == ["She now prefers masala chai in the evenings"]
    old = client.get("/api/v1/memories?include_superseded=true", headers=h).json()["memories"]
    sup = [m for m in old if m["id"] == first["id"]][0]
    assert sup["status"] == "superseded" and sup["superseded_by"] == ok.json()["memory"]["id"]


def test_keep_both_resolution_keeps_two_active_memories(client: TestClient, fake: FakeSupabase, env: None) -> None:
    h = ready_user(client, fake)
    enable_learning(client, h)
    cid, c = pending_chai(client, h)
    client.post(f"/api/v1/memory/candidates/{c['id']}/approve", json={}, headers=h)
    extractor(ScriptedExtractor([cand("She drinks masala chai with friends on weekends", "like masala chai in the mornings")]))
    review(client, h, cid)
    c2 = learning(client, h, cid)["candidates"][0]
    assert client.post(f"/api/v1/memory/candidates/{c2['id']}/approve", json={"resolution": "keep_both"}, headers=h).status_code == 201
    assert len(client.get("/api/v1/memories", headers=h).json()["memories"]) == 2


def test_forgetting_removes_the_text_blocks_resuggestion_and_removes_it_from_chat(client: TestClient, fake: FakeSupabase, env: None) -> None:
    h = ready_user(client, fake)
    enable_learning(client, h)
    cid, c = pending_chai(client, h)
    m = client.post(f"/api/v1/memory/candidates/{c['id']}/approve", json={}, headers=h).json()["memory"]
    assert client.delete(f"/api/v1/memories/{m['id']}?incorrect=true", headers=h).status_code == 204
    assert client.get("/api/v1/memories", headers=h).json()["memories"] == []
    tomb = [x for x in fake.tables["memory_candidates"] if x["id"] == c["id"]][0]
    assert tomb["status"] == "rejected" and tomb["statement"] == "" and tomb["rejected_reason"] == "incorrect"
    chat = ScriptedChat(["ok"])
    use(chat)
    send(client, h, cid, "tell me about chai", "key-77777777")
    assert "masala chai in the mornings" not in chat.calls[0][0].content
    extractor(ScriptedExtractor([cand("She likes masala chai in the mornings", "like masala chai in the mornings")]))
    review(client, h, cid)
    assert learning(client, h, cid)["candidates"] == []


# ---- deleting a conversation -------------------------------------------------------------------------------------------

def test_deleting_a_conversation_keeps_approved_memories_but_not_their_quotes_or_pending_ideas(client: TestClient, fake: FakeSupabase, env: None) -> None:
    h = ready_user(client, fake)
    enable_learning(client, h)
    cid, c = pending_chai(client, h)
    client.post(f"/api/v1/memory/candidates/{c['id']}/approve", json={}, headers=h)
    extractor(ScriptedExtractor([cand("She leaves loud parties early", "tired at loud parties", "m1")]))
    cid2 = chat_with(client, h, LOUD)
    review(client, h, cid2)
    assert client.delete(f"/api/v1/conversations/{cid}", headers=h).status_code == 204
    mem = client.get("/api/v1/memories", headers=h).json()["memories"][0]
    assert mem["source_deleted"] is True and mem["supporting"] == [] and mem["conversation_id"] is None
    assert client.delete(f"/api/v1/conversations/{cid2}", headers=h).status_code == 204
    assert client.get("/api/v1/memory/candidates", headers=h).json()["candidates"] == []      # unreviewed ideas are dropped


def test_deleting_a_conversation_can_also_delete_its_memories(client: TestClient, fake: FakeSupabase, env: None) -> None:
    h = ready_user(client, fake)
    enable_learning(client, h)
    cid, c = pending_chai(client, h)
    client.post(f"/api/v1/memory/candidates/{c['id']}/approve", json={}, headers=h)
    assert client.delete(f"/api/v1/conversations/{cid}?delete_memories=true", headers=h).status_code == 204
    assert client.get("/api/v1/memories", headers=h).json()["memories"] == []


# ---- profile refinements ------------------------------------------------------------------------------------------------

def approved_correction(client: TestClient, fake: FakeSupabase, h: dict[str, str]) -> dict[str, Any]:
    cid = chat_with(client, h, "No, I never use formal greetings with friends.", "I really keep my messages short and casual.")
    extractor(ScriptedExtractor([{
        "statement": "She never uses formal greetings with friends", "category": "communication_style", "scope": "friends",
        "evidence_type": "correction", "quotes": [{"message": "m1", "quote": "never use formal greetings with friends"}]}]))
    review(client, h, cid)
    c = learning(client, h, cid)["candidates"][0]
    return dict(client.post(f"/api/v1/memory/candidates/{c['id']}/approve", json={}, headers=h).json())


def test_a_correction_creates_a_proposal_and_never_changes_the_profile_by_itself(client: TestClient, fake: FakeSupabase, env: None) -> None:
    h = ready_user(client, fake)
    enable_learning(client, h)
    before = json.dumps(fake.tables["character_profiles"][0]["profile"], sort_keys=True)
    res = approved_correction(client, fake, h)
    p = res["profile_proposal"]
    assert p["status"] == "pending" and p["section"] == "speaking_style" and p["kind"] == "correction"
    assert json.dumps(fake.tables["character_profiles"][0]["profile"], sort_keys=True) == before
    assert fake.tables["profile_revisions"] == []
    assert client.get("/api/v1/profile-proposals", headers=h).json()["proposals"][0]["id"] == p["id"]


def test_accepting_a_proposal_snapshots_the_old_profile_and_leaves_the_description_alone(client: TestClient, fake: FakeSupabase, env: None) -> None:
    h = ready_user(client, fake)
    enable_learning(client, h)
    p = approved_correction(client, fake, h)["profile_proposal"]
    desc_before = [t["character_description"] for t in fake.tables["twins"]]
    r = client.post(f"/api/v1/profile-proposals/{p['id']}/resolve", json={"action": "accept", "text": "Skips formal greetings with friends"}, headers=h)
    assert r.status_code == 200 and r.json()["added"] == {"text": "Skips formal greetings with friends", "basis": "stated"}
    prof = fake.tables["character_profiles"][0]["profile"]
    assert prof["speaking_style"] == [{"text": "Skips formal greetings with friends", "basis": "stated"}]
    rev = client.get("/api/v1/profile-revisions", headers=h).json()["revisions"]
    assert len(rev) == 1 and rev[0]["reason"] == "proposal_accepted" and rev[0]["profile"]["speaking_style"] == []
    assert [t["character_description"] for t in fake.tables["twins"]] == desc_before
    assert client.post(f"/api/v1/profile-proposals/{p['id']}/resolve", json={"action": "accept"}, headers=h).json()["detail"]["code"] == "not_pending"


def test_reject_and_defer_leave_the_profile_untouched(client: TestClient, fake: FakeSupabase, env: None) -> None:
    h = ready_user(client, fake)
    enable_learning(client, h)
    p = approved_correction(client, fake, h)["profile_proposal"]
    assert client.post(f"/api/v1/profile-proposals/{p['id']}/resolve", json={"action": "defer"}, headers=h).json()["status"] == "deferred"
    assert len(client.get("/api/v1/profile-proposals", headers=h).json()["proposals"]) == 1       # deferred stays visible
    assert client.post(f"/api/v1/profile-proposals/{p['id']}/resolve", json={"action": "reject"}, headers=h).json()["status"] == "rejected"
    assert client.get("/api/v1/profile-proposals", headers=h).json()["proposals"] == []
    assert fake.tables["character_profiles"][0]["profile"]["speaking_style"] == [] and fake.tables["profile_revisions"] == []


def test_a_full_section_is_refused_and_a_forgotten_source_blocks_acceptance(client: TestClient, fake: FakeSupabase, env: None) -> None:
    h = ready_user(client, fake)
    enable_learning(client, h)
    fake.tables["character_profiles"][0]["profile"]["speaking_style"] = [{"text": f"entry {i}", "basis": "stated"} for i in range(8)]
    res = approved_correction(client, fake, h)
    p = res["profile_proposal"]
    r = client.post(f"/api/v1/profile-proposals/{p['id']}/resolve", json={"action": "accept"}, headers=h)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "section_full" and fake.tables["profile_revisions"] == []
    client.delete(f"/api/v1/memories/{res['memory']['id']}", headers=h)
    assert client.get("/api/v1/profile-proposals", headers=h).json()["proposals"] == []            # forgetting removes open proposals


def test_a_manual_proposal_can_target_a_section_and_only_for_an_active_memory(client: TestClient, fake: FakeSupabase, env: None) -> None:
    h = ready_user(client, fake)
    enable_learning(client, h)
    _, c = pending_chai(client, h)
    m = client.post(f"/api/v1/memory/candidates/{c['id']}/approve", json={}, headers=h).json()
    assert m["profile_proposal"] is None                        # an explicit statement doesn't auto-propose
    r = client.post(f"/api/v1/memories/{m['memory']['id']}/profile-proposal", json={"section": "interests_and_habits"}, headers=h)
    assert r.status_code == 201 and r.json()["profile_proposal"]["section"] == "interests_and_habits"
    again = client.post(f"/api/v1/memories/{m['memory']['id']}/profile-proposal", json={"section": "interests_and_habits"}, headers=h)
    assert again.json()["profile_proposal"]["id"] == r.json()["profile_proposal"]["id"]            # no duplicate
    assert client.post(f"/api/v1/memories/{m['memory']['id']}/profile-proposal", json={"section": "nope"}, headers=h).status_code == 422


def test_reanalysis_keeps_the_previous_profile_when_accepted_changes_would_be_replaced(client: TestClient, fake: FakeSupabase, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings
    from app.providers import consent_version
    from tests.helpers import analyze
    monkeypatch.setenv("AI_PROVIDER", "mock")
    get_settings.cache_clear()
    h = auth("alice")
    client.put("/api/v1/twin", json={"name": "Meera"}, headers=h)
    client.post("/api/v1/consents/ai-processing", json={"version": consent_version(get_settings())}, headers=h)
    assert client.put("/api/v1/twin/character", json={"description": DESC, "base_version": 0}, headers=h).status_code == 200
    assert analyze(client, h, 1).status_code == 200
    twin = fake.tables["twins"][0]
    fake.tables["character_profiles"][0]["profile"]["speaking_style"].append({"text": "accepted from chat", "basis": "stated"})
    fake.tables["profile_proposals"].append({"id": "pp1", "owner_id": "alice", "twin_id": twin["id"], "status": "accepted",
                                             "section": "speaking_style", "proposed_text": "accepted from chat"})
    assert client.put("/api/v1/twin/character", json={"description": DESC + " She also hums while cooking.", "base_version": 1}, headers=h).status_code == 200
    assert analyze(client, h, 2).status_code == 200
    rev = fake.tables["profile_revisions"]
    assert len(rev) == 1 and rev[0]["reason"] == "regenerated"
    assert {"text": "accepted from chat", "basis": "stated"} in rev[0]["profile"]["speaking_style"]


# ---- ownership -----------------------------------------------------------------------------------------------------------

def test_another_user_can_neither_see_nor_act_on_learning_data(client: TestClient, fake: FakeSupabase, env: None) -> None:
    ha = ready_user(client, fake, "alice")
    hb = ready_user(client, fake, "bob")
    enable_learning(client, ha)
    enable_learning(client, hb)
    cid, c = pending_chai(client, ha)
    m = client.post(f"/api/v1/memory/candidates/{c['id']}/approve", json={}, headers=ha).json()["memory"]
    extractor(ScriptedExtractor())
    assert review(client, hb, cid).status_code == 404
    assert client.get(f"/api/v1/conversations/{cid}/learning", headers=hb).status_code == 404
    assert client.get("/api/v1/memories", headers=hb).json()["memories"] == []
    assert client.get("/api/v1/memory/candidates", headers=hb).json()["candidates"] == []
    assert client.patch(f"/api/v1/memories/{m['id']}", json={"pinned": True}, headers=hb).status_code == 404
    assert client.delete(f"/api/v1/memories/{m['id']}", headers=hb).status_code == 404
    assert client.post(f"/api/v1/memories/{m['id']}/profile-proposal", json={"section": "core_traits"}, headers=hb).status_code == 404
    assert client.post(f"/api/v1/memory/candidates/{c['id']}/reject", json={}, headers=hb).status_code == 404
    assert client.get("/api/v1/profile-revisions", headers=hb).json()["revisions"] == []
    assert len(client.get("/api/v1/memories", headers=ha).json()["memories"]) == 1
