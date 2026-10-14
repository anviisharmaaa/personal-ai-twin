"""Provider selection, NVIDIA adapter and mock labelling. ALL MOCKED: no network, no real key, no cost.

A passing run here proves the request/response handling is coded as documented. It does NOT prove that NVIDIA's
hosted endpoint accepts this request; that is only proven by `python -m scripts.live_character_smoke`.
"""

import json
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.character import OUTPUT_JSON_SCHEMA, AnalysisError, CharacterProfile
from app.character_routes import _in_flight, get_analyzer
from app.config import Settings, get_settings
from app.main import app, create_app
from app.providers import (
    MockAnalyzer,
    NullAnalyzer,
    NvidiaAnalyzer,
    active_provider,
    build_analyzer,
    consent_version,
    provider_info,
)
from tests.conftest import auth
from tests.fake_supabase import FakeSupabase

TEXT = "She is warm and teasing with close friends, but quiet and careful around people she has just met."
GOOD = {"summary": "Warm with friends, reserved with strangers.",
        "core_traits": [{"text": "Warm with close friends", "basis": "stated"}]}


def settings(**kw: str) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg]


def nvidia(handler: Callable[[httpx.Request], httpx.Response], mode: str = "guided_json") -> NvidiaAnalyzer:
    return NvidiaAnalyzer("nvapi-test-secret", "nvidia/test-model", 5, 500, json_mode=mode,
                          transport=httpx.MockTransport(handler))


def ok_response(content: str, usage: dict[str, int] | None = None) -> httpx.Response:
    return httpx.Response(200, json={"model": "nvidia/test-model", "choices": [
        {"finish_reason": "stop", "message": {"content": content}}],
        "usage": usage or {"prompt_tokens": 11, "completion_tokens": 22}})


# ---- selection -------------------------------------------------------------------------------------------

def test_provider_is_explicit_and_never_inferred_from_keys() -> None:
    s = settings(nvidia_api_key="k", nvidia_character_model="m", openai_api_key="k2", openai_character_model="m2")
    assert active_provider(s) == "" and isinstance(build_analyzer(s), NullAnalyzer)
    assert build_analyzer(s).configured is False


def test_each_provider_builds_its_own_analyzer_and_needs_its_own_settings() -> None:
    s = settings(ai_provider="nvidia", nvidia_api_key="k", nvidia_character_model="nvidia/x")
    a = build_analyzer(s)
    assert isinstance(a, NvidiaAnalyzer) and a.configured and a.provider == "nvidia"
    # Chosen provider missing its own settings -> not configured. It does NOT borrow another provider's key.
    s2 = settings(ai_provider="nvidia", openai_api_key="k", openai_character_model="m")
    assert build_analyzer(s2).configured is False
    s3 = settings(ai_provider="openai", openai_api_key="k", openai_character_model="m")
    assert build_analyzer(s3).provider == "openai"


def test_mock_is_refused_in_production_and_unknown_values_mean_off() -> None:
    assert active_provider(settings(ai_provider="mock")) == "mock"
    assert active_provider(settings(ai_provider="mock", app_env="production")) == ""
    assert active_provider(settings(ai_provider="gemini")) == ""


def test_consent_version_and_wording_are_provider_specific() -> None:
    nv, op = settings(ai_provider="nvidia"), settings(ai_provider="openai")
    assert consent_version(nv) != consent_version(op) != consent_version(settings())
    assert "NVIDIA" in " ".join(provider_info(nv)["disclosure"]) and provider_info(nv)["external"] is True
    assert "OpenAI" not in " ".join(provider_info(nv)["disclosure"])
    assert provider_info(settings(ai_provider="mock"))["external"] is False


# ---- NVIDIA adapter (mocked transport) --------------------------------------------------------------------

@pytest.mark.anyio
async def test_nvidia_request_shape_guided_json() -> None:
    seen: dict[str, object] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"] = str(req.url), req.headers.get("authorization")
        seen["body"] = json.loads(req.content)
        return ok_response(json.dumps(GOOD))

    r = await nvidia(handler).analyze(TEXT)
    body = seen["body"]
    assert isinstance(body, dict)
    assert seen["url"] == "https://integrate.api.nvidia.com/v1/chat/completions"
    assert seen["auth"] == "Bearer nvapi-test-secret"
    assert body["model"] == "nvidia/test-model" and body["max_tokens"] == 500 and body["stream"] is False
    assert body["nvext"] == {"guided_json": OUTPUT_JSON_SCHEMA}
    assert "response_format" not in body and "max_completion_tokens" not in body
    assert TEXT in body["messages"][1]["content"]
    assert r.provider == "nvidia" and r.input_tokens == 11 and r.output_tokens == 22


@pytest.mark.anyio
async def test_nvidia_prompt_mode_puts_schema_in_prompt_instead() -> None:
    seen: dict[str, object] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(req.content)
        return ok_response(json.dumps(GOOD))

    await nvidia(handler, "prompt").analyze(TEXT)
    body = seen["body"]
    assert isinstance(body, dict) and "nvext" not in body
    assert "JSON Schema" in body["messages"][0]["content"]


@pytest.mark.anyio
@pytest.mark.parametrize("content", [
    json.dumps(GOOD),
    "<think>weighing the details…</think>\n" + json.dumps(GOOD),
    "```json\n" + json.dumps(GOOD) + "\n```",
])
async def test_nvidia_accepts_valid_json_even_when_wrapped(content: str) -> None:
    r = await nvidia(lambda _: ok_response(content)).analyze(TEXT)
    assert r.profile.summary.startswith("Warm")


@pytest.mark.anyio
@pytest.mark.parametrize("content", ["Sure! Here is the profile: {}", "{not json", json.dumps({"summary": 5}),
                                     json.dumps({**GOOD, "surprise": 1})])
async def test_nvidia_rejects_malformed_output_without_repairing_or_retrying(content: str) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return ok_response(content)

    with pytest.raises(AnalysisError) as e:
        await nvidia(handler).analyze(TEXT)
    assert e.value.code == "malformed_response" and calls == 1


@pytest.mark.anyio
@pytest.mark.parametrize(("status", "code"), [(401, "provider_auth"), (403, "provider_auth"),
                                              (429, "rate_limited"), (402, "quota_exhausted"),
                                              (400, "provider_rejected"), (404, "provider_rejected"),
                                              (422, "provider_rejected")])
async def test_nvidia_error_mapping_and_no_retry_on_quota_or_client_errors(status: int, code: str) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, json={"detail": "x"})

    with pytest.raises(AnalysisError) as e:
        await nvidia(handler).analyze(TEXT)
    assert e.value.code == code and calls == 1


@pytest.mark.anyio
async def test_nvidia_retries_a_server_error_once_then_succeeds_or_fails() -> None:
    calls = 0

    def flaky(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503) if calls == 1 else ok_response(json.dumps(GOOD))

    assert (await nvidia(flaky).analyze(TEXT)).provider == "nvidia" and calls == 2
    calls = 0
    with pytest.raises(AnalysisError) as e:
        await nvidia(lambda _: (_ for _ in ()).throw(httpx.ConnectError("down"))).analyze(TEXT)
    assert e.value.code == "provider_unreachable"


@pytest.mark.anyio
async def test_nvidia_truncation_is_reported_not_parsed() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"finish_reason": "length", "message": {"content": '{"summ'}}]})

    with pytest.raises(AnalysisError) as e:
        await nvidia(handler).analyze(TEXT)
    assert e.value.code == "truncated"


@pytest.mark.anyio
async def test_nvidia_unconfigured_makes_no_request() -> None:
    def boom(_: httpx.Request) -> httpx.Response:
        raise AssertionError("network used")

    a = NvidiaAnalyzer("", "", 5, 100, transport=httpx.MockTransport(boom))
    with pytest.raises(AnalysisError) as e:
        await a.analyze(TEXT)
    assert e.value.code == "not_configured"


@pytest.mark.anyio
async def test_the_key_and_description_never_appear_in_error_text_or_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("DEBUG")
    with pytest.raises(AnalysisError) as e:
        await nvidia(lambda _: httpx.Response(401, json={"error": "bad nvapi-test-secret"})).analyze(TEXT)
    assert "nvapi-test-secret" not in e.value.message and TEXT not in e.value.message
    assert "nvapi-test-secret" not in caplog.text and TEXT not in caplog.text


# ---- mock provider ----------------------------------------------------------------------------------------

@pytest.mark.anyio
async def test_mock_makes_no_network_call_ignores_the_description_and_labels_itself() -> None:
    r = await MockAnalyzer().analyze("SECRET-DESCRIPTION-TEXT")
    assert r.provider == "mock" and "SECRET-DESCRIPTION-TEXT" not in r.profile.model_dump_json()
    assert r.profile.summary.startswith("SAMPLE ONLY")
    assert isinstance(r.profile, CharacterProfile)


# ---- routes: labelling, no cross-provider reuse, no fallback ----------------------------------------------

@pytest.fixture
def mock_mode(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("AI_PROVIDER", "mock")
    get_settings.cache_clear()
    app.dependency_overrides.pop(get_analyzer, None)
    _in_flight.clear()
    yield
    get_settings.cache_clear()


def start(client: TestClient, user: str = "alice") -> dict[str, str]:
    h = auth(user)
    client.put("/api/v1/twin", json={"name": "Meera"}, headers=h)
    version = consent_version(get_settings())
    assert client.post("/api/v1/consents/ai-processing", json={"version": version}, headers=h).status_code == 201
    client.put("/api/v1/twin/character", json={"description": TEXT, "base_version": 0}, headers=h)
    return h


def test_mock_result_is_labelled_a_sample_in_the_api(client: TestClient, mock_mode: None) -> None:
    h = start(client)
    r = client.post("/api/v1/twin/character/analyze", json={"version": 1}, headers=h)
    assert r.status_code == 200
    c = r.json()["character"]
    assert c["generated_by"] == {"provider": "mock", "model": "sample-fixture", "is_sample": True}
    assert client.get("/api/v1/me", headers=h).json()["ai_consent"]["provider"]["id"] == "mock"


def test_changing_provider_requires_new_consent_and_never_reuses_a_sample_profile(
        client: TestClient, mock_mode: None, monkeypatch: pytest.MonkeyPatch, fake: FakeSupabase) -> None:
    h = start(client)
    client.post("/api/v1/twin/character/analyze", json={"version": 1}, headers=h)
    # Switch the server to NVIDIA (not configured: no key). The old mock consent no longer counts.
    monkeypatch.setenv("AI_PROVIDER", "nvidia")
    get_settings.cache_clear()
    me = client.get("/api/v1/me", headers=h).json()
    assert me["ai_consent"]["granted"] is False and me["ai_consent"]["provider"]["id"] == "nvidia"
    r = client.post("/api/v1/twin/character/analyze", json={"version": 1}, headers=h)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "consent_required"
    # The sample profile is still there for review, still labelled as a sample.
    assert me["character"]["generated_by"]["is_sample"] is True
    # With consent but no key, we get an honest 503. We do NOT fall back to the mock or to OpenAI.
    client.post("/api/v1/consents/ai-processing", json={"version": consent_version(get_settings())}, headers=h)
    r = client.post("/api/v1/twin/character/analyze", json={"version": 1}, headers=h)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "not_configured"
    assert client.get("/api/v1/me", headers=h).json()["character"]["profile"]["summary"].startswith("SAMPLE ONLY")


def test_ready_reports_provider_and_warns_when_a_key_has_no_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-secret")
    get_settings.cache_clear()
    body = TestClient(create_app()).get("/ready").json()
    assert body["ai_provider"] == "none" and body["configured"]["ai"] is False
    assert any("AI_PROVIDER" in w for w in body["warnings"]) and "nvapi-secret" not in json.dumps(body)
    monkeypatch.setenv("AI_PROVIDER", "nvidia")
    monkeypatch.setenv("NVIDIA_CHARACTER_MODEL", "nvidia/test-model")
    get_settings.cache_clear()
    body = TestClient(create_app()).get("/ready").json()
    assert body["ai_provider"] == "nvidia" and body["configured"]["ai"] is True and body["warnings"] == []
    get_settings.cache_clear()


# ---- reasoning disabled / token budget / truncation (live run showed reasoning eating the whole budget) -------

@pytest.mark.anyio
async def test_nvidia_request_disables_reasoning_with_the_documented_field_only() -> None:
    seen: dict[str, object] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(req.content)
        return ok_response(json.dumps(GOOD), {"prompt_tokens": 400, "completion_tokens": 300})

    s = settings(ai_provider="nvidia", nvidia_api_key="k", nvidia_character_model="nvidia/nemotron-3-super-120b-a12b",
                 nvidia_json_mode="prompt")
    a = build_analyzer(s)
    a._transport = httpx.MockTransport(handler)  # type: ignore[attr-defined]
    r = await a.analyze(TEXT)
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert "reasoning_effort" not in body  # not documented for this model, so never sent
    assert body["max_tokens"] == 4096 and "max_completion_tokens" not in body
    assert body["model"] == "nvidia/nemotron-3-super-120b-a12b"
    assert "nvext" not in body and "JSON Schema" in body["messages"][0]["content"]  # prompt mode unchanged
    assert r.profile.summary.startswith("Warm") and r.output_tokens == 300 and r.finish_reason == "stop"


@pytest.mark.anyio
async def test_reasoning_is_disabled_in_guided_json_mode_too() -> None:
    seen: dict[str, object] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(req.content)
        return ok_response(json.dumps(GOOD))

    await nvidia(handler, "guided_json").analyze(TEXT)
    assert isinstance(seen["body"], dict) and seen["body"]["chat_template_kwargs"] == {"enable_thinking": False}


def test_nvidia_token_budget_default_and_hard_bounds() -> None:
    assert settings().nvidia_max_output_tokens == 4096
    assert settings(nvidia_max_output_tokens="6000").nvidia_max_output_tokens == 6000
    for bad in ("100", "100000"):  # too small to hold a profile / large enough to hide a reasoning problem
        with pytest.raises(ValueError):
            settings(nvidia_max_output_tokens=bad)


@pytest.mark.anyio
@pytest.mark.parametrize("message", [{"content": None}, {"content": ""}, {"content": '{"summary": "Wa'}])
async def test_genuine_truncation_fails_safely_whatever_the_partial_content(message: dict[str, object]) -> None:
    """Includes the exact live failure: completion_tokens == reasoning_tokens == budget and no final answer."""
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"choices": [{"finish_reason": "length", "message": message}],
                                         "usage": {"prompt_tokens": 500, "completion_tokens": 3000,
                                                   "completion_tokens_details": {"reasoning_tokens": 3000}}})

    with pytest.raises(AnalysisError) as e:
        await nvidia(handler).analyze(TEXT)
    assert e.value.code == "truncated" and e.value.status_code == 502
    assert calls == 1  # no automatic retry of a call that already used its whole budget
    assert TEXT not in e.value.message and "nvapi" not in (e.value.detail or "")


@pytest.mark.anyio
async def test_reasoning_tokens_are_reported_when_the_provider_returns_them() -> None:
    usage = {"prompt_tokens": 10, "completion_tokens": 50, "completion_tokens_details": {"reasoning_tokens": 7}}
    r = await nvidia(lambda _: ok_response(json.dumps(GOOD), usage)).analyze(TEXT)
    assert r.reasoning_tokens == 7  # lets the smoke test warn if the endpoint ignored enable_thinking=false


def test_truncated_analysis_keeps_the_last_good_profile_and_the_users_text(client: TestClient) -> None:
    good = nvidia(lambda _: ok_response(json.dumps(GOOD)))
    cut = nvidia(lambda _: httpx.Response(200, json={"choices": [{"finish_reason": "length",
                                                                   "message": {"content": None}}]}))
    _in_flight.clear()
    get_settings.cache_clear()
    h = start(client)
    app.dependency_overrides[get_analyzer] = lambda: good
    assert client.post("/api/v1/twin/character/analyze", json={"version": 1}, headers=h).status_code == 200
    before = client.get("/api/v1/me", headers=h).json()["character"]["profile"]
    assert before["summary"].startswith("Warm")

    edited = TEXT + " She also hates being rushed."
    client.put("/api/v1/twin/character", json={"description": edited, "base_version": 1}, headers=h)
    app.dependency_overrides[get_analyzer] = lambda: cut
    r = client.post("/api/v1/twin/character/analyze", json={"version": 2}, headers=h)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "truncated"

    me = client.get("/api/v1/me", headers=h).json()
    assert me["twin"]["character_description"] == edited            # the user's words are untouched
    assert me["character"]["profile"] == before                     # last good profile not overwritten
    assert me["character"]["status"] == "outdated"                  # and honestly marked as made from older text
    assert me["character"]["failure"] == "truncated"
    get_settings.cache_clear()


def test_tests_ignore_the_developers_env_file_and_environment(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Guard for the isolation fixture: a real-looking provider in .env or the shell must not reach mocked tests."""
    import os

    env = tmp_path / ".env"
    env.write_text("AI_PROVIDER=nvidia\nNVIDIA_API_KEY=nvapi-not-real\n")
    monkeypatch.chdir(env.parent)                 # Settings looks for ".env" in the working directory
    get_settings.cache_clear()
    s = get_settings()
    assert s.ai_provider == "" and s.nvidia_api_key == "" and consent_version(s) == "2026-10-v3-none"
    assert not any(k.startswith(("NVIDIA_", "OPENAI_")) for k in os.environ)
