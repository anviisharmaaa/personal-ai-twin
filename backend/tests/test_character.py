"""Character description + analysis. MOCKED: Supabase is FakeSupabase and the model is FakeAnalyzer.

Nothing here proves a real OpenAI call works; see OpenAIAnalyzer tests (also mocked transport) and the
README's live-verification checklist for what still needs a real key.
"""

import json
from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from app.character import (
    OUTPUT_JSON_SCHEMA,
    AnalysisError,
    AnalysisResult,
    CharacterProfile,
    OpenAIAnalyzer,
    parse_profile,
)
from app.character_routes import _in_flight, get_analyzer
from app.config import get_settings
from app.main import app
from tests.conftest import auth
from tests.fake_supabase import FakeSupabase

CONSENT = "2026-10-v3-none"  # tests run with AI_PROVIDER unset; the version is provider-specific
TEXT = "She is warm and teasing with close friends, but quiet and careful around people she has just met."
GOOD = {"summary": "Warm with friends, reserved with strangers.",
        "core_traits": [{"text": "Warm with close friends", "basis": "stated"}],
        "context_tendencies": [{"context": "With strangers", "tendency": "Reserved", "basis": "stated",
                                "evidence": "quiet and careful around people she has just met"}]}


class FakeAnalyzer:
    """MOCK provider. Counts calls so tests can prove when the model was (not) invoked."""

    def __init__(self) -> None:
        self.calls = 0
        self.error: AnalysisError | None = None
        self.is_configured = True
        self.seen: list[str] = []

    @property
    def configured(self) -> bool:
        return self.is_configured

    async def analyze(self, description: str) -> AnalysisResult:
        self.calls += 1
        self.seen.append(description)
        if self.error:
            raise self.error
        return AnalysisResult(CharacterProfile.model_validate(GOOD), "fake-model", 100, 50, 12)


@pytest.fixture
def analyzer(client: TestClient) -> Iterator[FakeAnalyzer]:
    a = FakeAnalyzer()
    app.dependency_overrides[get_analyzer] = lambda: a
    _in_flight.clear()
    get_settings.cache_clear()
    yield a
    get_settings.cache_clear()


def setup_twin(client: TestClient, user: str = "alice", consent: bool = True) -> dict[str, str]:
    h = auth(user)
    client.put("/api/v1/twin", json={"name": "Anvi"}, headers=h)
    if consent:
        client.post("/api/v1/consents/ai-processing", json={"version": CONSENT}, headers=h)
    return h


def save(client: TestClient, h: dict[str, str], text: str, base: int) -> httpx.Response:
    return client.put("/api/v1/twin/character", json={"description": text, "base_version": base}, headers=h)


def test_save_versions_and_status(client: TestClient, analyzer: FakeAnalyzer) -> None:
    h = setup_twin(client)
    me = client.get("/api/v1/me", headers=h).json()
    assert me["character"]["status"] == "empty" and me["character"]["description_version"] == 0
    r = save(client, h, TEXT, 0)
    assert r.status_code == 200 and r.json()["character"]["status"] == "not_analysed"
    assert r.json()["character"]["description_version"] == 1
    # Saving identical text is a no-op (no version bump), and a stale base is rejected.
    assert save(client, h, TEXT, 1).json()["character"]["description_version"] == 1
    stale = save(client, h, TEXT + " More.", 0)
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "changed_elsewhere"
    assert client.post("/api/v1/onboarding/steps/personality/complete", headers=h).status_code == 200


def test_step_requires_a_saved_description(client: TestClient) -> None:
    h = setup_twin(client)
    assert client.post("/api/v1/onboarding/steps/personality/complete", headers=h).status_code == 409


def test_description_is_bounded_and_strict(client: TestClient) -> None:
    h = setup_twin(client)
    assert save(client, h, "x" * 8001, 0).status_code == 422
    assert client.put("/api/v1/twin/character", json={"description": "a", "base_version": 0, "owner_id": "bob"},
                      headers=h).status_code == 422
    assert client.put("/api/v1/twin/character", json={"description": "a"}, headers=h).status_code == 422


def test_requires_a_twin(client: TestClient, analyzer: FakeAnalyzer) -> None:
    h = auth("alice")
    assert save(client, h, TEXT, 0).status_code == 409
    assert client.post("/api/v1/twin/character/analyze", json={"version": 1}, headers=h).status_code == 409


def test_auth_required(client: TestClient, analyzer: FakeAnalyzer) -> None:
    assert client.put("/api/v1/twin/character", json={"description": "a", "base_version": 0}).status_code == 401
    assert client.post("/api/v1/twin/character/analyze", json={"version": 1}).status_code == 401


def test_analysis_blocked_without_consent_and_after_withdrawal(client: TestClient, analyzer: FakeAnalyzer) -> None:
    h = setup_twin(client, consent=False)
    save(client, h, TEXT, 0)
    r = client.post("/api/v1/twin/character/analyze", json={"version": 1}, headers=h)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "consent_required"
    assert analyzer.calls == 0
    client.post("/api/v1/consents/ai-processing", json={"version": CONSENT}, headers=h)
    assert client.post("/api/v1/twin/character/analyze", json={"version": 1}, headers=h).status_code == 200
    client.delete("/api/v1/consents/ai-processing", headers=h)
    save(client, h, TEXT + " Changed.", 1)
    r = client.post("/api/v1/twin/character/analyze", json={"version": 2}, headers=h)
    assert r.status_code == 403 and analyzer.calls == 1  # withdrawal respected; nothing sent


def test_missing_configuration_is_explicit_not_faked(client: TestClient, analyzer: FakeAnalyzer) -> None:
    h = setup_twin(client)
    save(client, h, TEXT, 0)
    analyzer.is_configured = False
    r = client.post("/api/v1/twin/character/analyze", json={"version": 1}, headers=h)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "not_configured"
    assert client.get("/api/v1/me", headers=h).json()["character"]["profile"] is None


def test_input_validation(client: TestClient, analyzer: FakeAnalyzer) -> None:
    h = setup_twin(client)
    save(client, h, "Too short.", 0)
    r = client.post("/api/v1/twin/character/analyze", json={"version": 1}, headers=h)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "too_short"
    save(client, h, TEXT, 1)
    r = client.post("/api/v1/twin/character/analyze", json={"version": 1}, headers=h)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "stale_version"
    assert analyzer.calls == 0


def test_analyse_cache_regenerate_and_outdated(client: TestClient, analyzer: FakeAnalyzer, fake: FakeSupabase) -> None:
    h = setup_twin(client)
    save(client, h, TEXT, 0)
    r = client.post("/api/v1/twin/character/analyze", json={"version": 1}, headers=h).json()
    assert r["cached"] is False and r["character"]["status"] == "current"
    assert r["character"]["profile"]["summary"].startswith("Warm") and analyzer.seen == [TEXT]
    # Same text again: served from storage, the model is not called a second time.
    r = client.post("/api/v1/twin/character/analyze", json={"version": 1}, headers=h).json()
    assert r["cached"] is True and analyzer.calls == 1
    # Editing makes the stored profile outdated but keeps it, and the original text is untouched.
    out = save(client, h, TEXT + " She hates being rushed.", 1).json()["character"]
    assert out["status"] == "outdated" and out["profile"] is not None and out["profile_version"] == 1
    twin = [t for t in fake.tables["twins"] if t["owner_id"] == "alice"][0]
    assert twin["character_description"].endswith("rushed.")
    # Regenerating produces a profile for the latest version.
    r = client.post("/api/v1/twin/character/analyze", json={"version": 2}, headers=h).json()
    assert r["character"]["status"] == "current" and r["character"]["profile_version"] == 2 and analyzer.calls == 2
    # Usage ledger holds numbers only, never content.
    usage = fake.tables["ai_usage"]
    assert len(usage) == 2 and all(set(u) >= {"input_tokens", "output_tokens"} for u in usage)
    assert not any(TEXT in json.dumps(u) for u in usage)


def test_failure_keeps_last_good_profile(client: TestClient, analyzer: FakeAnalyzer) -> None:
    h = setup_twin(client)
    save(client, h, TEXT, 0)
    client.post("/api/v1/twin/character/analyze", json={"version": 1}, headers=h)
    save(client, h, TEXT + " Extra detail here.", 1)
    analyzer.error = AnalysisError("timeout", "The AI took too long to respond. Please try again.", 504)
    r = client.post("/api/v1/twin/character/analyze", json={"version": 2}, headers=h)
    assert r.status_code == 504 and r.json()["detail"]["code"] == "timeout"
    c = client.get("/api/v1/me", headers=h).json()["character"]
    assert c["status"] == "outdated" and c["profile"]["summary"] and c["profile_version"] == 1
    assert c["failure"] == "timeout"
    # A later success clears the failure.
    analyzer.error = None
    c = client.post("/api/v1/twin/character/analyze", json={"version": 2}, headers=h).json()["character"]
    assert c["status"] == "current" and c["failure"] is None


def test_failure_with_no_prior_profile(client: TestClient, analyzer: FakeAnalyzer) -> None:
    h = setup_twin(client)
    save(client, h, TEXT, 0)
    analyzer.error = AnalysisError("malformed_response", "bad", 502)
    assert client.post("/api/v1/twin/character/analyze", json={"version": 1}, headers=h).status_code == 502
    c = client.get("/api/v1/me", headers=h).json()["character"]
    assert c["status"] == "not_analysed" and c["profile"] is None and c["failure"] == "malformed_response"


def test_in_flight_and_daily_limit(client: TestClient, analyzer: FakeAnalyzer, fake: FakeSupabase,
                                   monkeypatch: pytest.MonkeyPatch) -> None:
    h = setup_twin(client)
    save(client, h, TEXT, 0)
    twin_id = [t for t in fake.tables["twins"] if t["owner_id"] == "alice"][0]["id"]
    _in_flight.add(twin_id)
    r = client.post("/api/v1/twin/character/analyze", json={"version": 1}, headers=h)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "in_progress" and analyzer.calls == 0
    _in_flight.clear()
    monkeypatch.setenv("ANALYSIS_DAILY_LIMIT", "1")
    get_settings.cache_clear()
    assert client.post("/api/v1/twin/character/analyze", json={"version": 1}, headers=h).status_code == 200
    save(client, h, TEXT + " Edited.", 1)
    r = client.post("/api/v1/twin/character/analyze", json={"version": 2}, headers=h)
    assert r.status_code == 429 and r.json()["detail"]["code"] == "daily_limit" and analyzer.calls == 1


def test_kill_switch(client: TestClient, analyzer: FakeAnalyzer, monkeypatch: pytest.MonkeyPatch) -> None:
    h = setup_twin(client)
    save(client, h, TEXT, 0)
    monkeypatch.setenv("AI_ENABLED", "false")
    get_settings.cache_clear()
    r = client.post("/api/v1/twin/character/analyze", json={"version": 1}, headers=h)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "ai_disabled" and analyzer.calls == 0


def test_users_cannot_see_each_others_characters(client: TestClient, analyzer: FakeAnalyzer) -> None:
    a, b = setup_twin(client, "alice"), setup_twin(client, "bob")
    save(client, a, TEXT, 0)
    client.post("/api/v1/twin/character/analyze", json={"version": 1}, headers=a)
    cb = client.get("/api/v1/me", headers=b).json()
    assert cb["twin"]["character_description"] == "" and cb["character"]["profile"] is None


# ---- Provider adapter (MOCKED HTTP transport; not a live OpenAI call) ----

def provider(handler, **kw) -> OpenAIAnalyzer:  # type: ignore[no-untyped-def]
    return OpenAIAnalyzer("sk-test", "test-model", 5.0, 500, transport=httpx.MockTransport(handler), **kw)


def ok_response(content: str, finish: str = "stop") -> httpx.Response:
    return httpx.Response(200, json={"model": "test-model-2026", "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                                     "choices": [{"finish_reason": finish, "message": {"content": content}}]})


@pytest.mark.anyio
async def test_adapter_request_shape_and_parse() -> None:
    seen: dict[str, object] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["auth"] = req.headers["authorization"]
        seen["body"] = json.loads(req.content)
        return ok_response(json.dumps(GOOD | {k: [] for k in OUTPUT_JSON_SCHEMA["required"] if k not in GOOD}))

    res = await provider(handler).analyze(TEXT)
    body = seen["body"]
    assert seen["auth"] == "Bearer sk-test" and body["model"] == "test-model"  # type: ignore[index]
    assert body["response_format"]["json_schema"]["strict"] is True  # type: ignore[index]
    assert TEXT in body["messages"][1]["content"]  # type: ignore[index]
    assert res.profile.summary and res.input_tokens == 10 and res.model == "test-model-2026"


@pytest.mark.anyio
@pytest.mark.parametrize(("make", "code"), [
    (lambda: ok_response("not json"), "not_json"),
    (lambda: ok_response(json.dumps({"summary": "x", "extra": 1})), "schema_invalid"),
    (lambda: ok_response("{}", finish="length"), "truncated"),
    (lambda: httpx.Response(429), "rate_limited"),
    (lambda: httpx.Response(401), "provider_auth"),
    (lambda: httpx.Response(404), "provider_rejected"),
    (lambda: httpx.Response(500), "provider_error"),
])
async def test_adapter_failures(make, code) -> None:  # type: ignore[no-untyped-def]
    calls = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return make()

    with pytest.raises(AnalysisError) as e:
        await provider(handler).analyze("hello")
    assert e.value.code == code
    assert calls["n"] == (2 if code == "provider_error" else 1)  # retry only transient 5xx, once


@pytest.mark.anyio
async def test_adapter_unconfigured_makes_no_request() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise AssertionError("must not call out")

    a = OpenAIAnalyzer("sk-test", "", 5.0, 500, transport=httpx.MockTransport(handler))
    with pytest.raises(AnalysisError) as e:
        await a.analyze("hi")
    assert e.value.code == "not_configured"


def test_profile_limits_enforced() -> None:
    with pytest.raises(AnalysisError):
        parse_profile(json.dumps({"summary": "x" * 1001}))
    p = parse_profile(json.dumps({"summary": "ok"}))
    assert p.core_traits == [] and p.uncertainties == []  # unknown stays empty, nothing invented


def test_old_consent_version_must_be_reaccepted(client: TestClient, analyzer: FakeAnalyzer,
                                                fake: FakeSupabase) -> None:
    h = setup_twin(client, consent=False)
    fake.tables["consents"].append({"id": "c0", "user_id": "alice", "kind": "ai_processing", "version": "2026-10-v1",
                                    "granted_at": "2026-10-01T00:00:00Z", "withdrawn_at": None})
    save(client, h, TEXT, 0)
    assert client.get("/api/v1/me", headers=h).json()["ai_consent"]["granted"] is False
    r = client.post("/api/v1/twin/character/analyze", json={"version": 1}, headers=h)
    assert r.status_code == 403 and analyzer.calls == 0
    assert client.post("/api/v1/consents/ai-processing", json={"version": CONSENT}, headers=h).status_code == 201
    assert client.get("/api/v1/me", headers=h).json()["ai_consent"]["granted"] is True
    assert client.post("/api/v1/twin/character/analyze", json={"version": 1}, headers=h).status_code == 200


def test_ready_reports_character_model_and_warns_about_the_old_name(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.main import create_app

    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_CHAT_MODEL", "some-model")  # the retired name must NOT enable character analysis
    monkeypatch.delenv("OPENAI_CHARACTER_MODEL", raising=False)
    get_settings.cache_clear()
    body = TestClient(create_app()).get("/ready").json()
    assert body["configured"]["ai"] is False
    assert any("OPENAI_CHARACTER_MODEL" in w for w in body["warnings"])
    assert "sk-test" not in json.dumps(body)
    monkeypatch.setenv("OPENAI_CHARACTER_MODEL", "gpt-6-luna")
    get_settings.cache_clear()
    body = TestClient(create_app()).get("/ready").json()
    assert body["configured"]["ai"] is True and body["warnings"] == []
    get_settings.cache_clear()


@pytest.mark.anyio
async def test_provider_error_detail_is_captured_for_operators_but_not_the_user_message() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"type": "invalid_request_error", "param": "max_completion_tokens",
                                                   "message": "Unsupported parameter"}})

    with pytest.raises(AnalysisError) as e:
        await provider(handler).analyze("hello")
    assert "max_completion_tokens" in (e.value.detail or "") and "max_completion_tokens" not in e.value.message
