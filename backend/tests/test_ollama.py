# ruff: noqa: E501
"""Ollama (local model) provider. ALL MOCKED: no Ollama server is contacted and no model is run.

These tests prove the adapter builds the right request, only talks to an approved local address, reports clear errors,
and feeds the shared grounding pipeline. They do NOT prove that any particular local model produces good profiles;
that needs a real local run (docs/LIVE_VERIFICATION.md, section "Ollama").
"""

import json
from collections.abc import Callable

import httpx
import pytest
from fastapi.testclient import TestClient

from app.character import OUTPUT_JSON_SCHEMA, AnalysisError
from app.character_routes import _in_flight, get_analyzer
from app.config import Settings, get_settings
from app.main import app, create_app
from app.providers import (
    NullAnalyzer,
    OllamaAnalyzer,
    active_provider,
    build_analyzer,
    consent_version,
    ollama_endpoint_ok,
    ollama_is_local,
    provider_info,
    provider_model,
)
from tests.test_grounding import RICH, item
from tests.test_providers import start


def settings(**kw: object) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg]


def ollama(handler: Callable[[httpx.Request], httpx.Response], **kw: object) -> OllamaAnalyzer:
    return OllamaAnalyzer("http://localhost:11434/v1", "qwen-test:9b", 5, 1024, transport=httpx.MockTransport(handler),
                          **kw)  # type: ignore[arg-type]


def body_for(profile: dict[str, object], usage: dict[str, int] | None = None) -> httpx.Response:
    full = {"summary": "S", **{k: [] for k in OUTPUT_JSON_SCHEMA["required"] if k != "summary"}, **profile}
    return httpx.Response(200, json={"model": "qwen-test:9b", "choices": [
        {"finish_reason": "stop", "message": {"content": json.dumps(full)}}],
        "usage": usage or {"prompt_tokens": 4000, "completion_tokens": 200}})


# ---- explicit selection, no key, no fallback ---------------------------------------------------------------------

def test_ollama_is_selected_only_explicitly_and_needs_only_a_model() -> None:
    assert isinstance(build_analyzer(settings(ollama_character_model="m")), NullAnalyzer)      # not chosen -> AI off
    s = settings(ai_provider="ollama", ollama_character_model="qwen3.5:9b")
    a = build_analyzer(s)
    assert isinstance(a, OllamaAnalyzer) and a.configured and a.provider == "ollama"
    assert provider_model(s) == "qwen3.5:9b"
    assert build_analyzer(settings(ai_provider="ollama")).configured is False                    # no model installed/named
    # Another provider's key never enables it, and its own settings never leak into another provider.
    assert build_analyzer(settings(ai_provider="ollama", nvidia_api_key="k", nvidia_character_model="m")).configured is False
    assert build_analyzer(settings(ai_provider="nvidia", ollama_character_model="m")).configured is False


@pytest.mark.parametrize("url,ok", [
    ("http://localhost:11434/v1", True), ("http://127.0.0.1:11434/v1", True), ("http://[::1]:11434/v1", True),
    ("http://127.1.2.3:11434/v1", True), ("https://localhost/v1", True),
    ("http://example.com/v1", False), ("http://192.168.1.20:11434/v1", False), ("http://0.0.0.0:11434/v1", False),
    ("http://localhost@evil.example/v1", False), ("http://user:pw@localhost/v1", False),
    ("http://localhost.evil.example/v1", False), ("ftp://localhost/v1", False), ("localhost:11434", False), ("", False),
])
def test_only_loopback_addresses_are_accepted_by_default(url: str, ok: bool) -> None:
    assert ollama_is_local(url) is ok
    s = settings(ai_provider="ollama", ollama_character_model="m", ollama_base_url=url)
    assert ollama_endpoint_ok(s) is ok and build_analyzer(s).configured is ok


def test_a_remote_ollama_needs_an_explicit_opt_in_and_gets_its_own_consent_and_disclosure() -> None:
    base = dict(ai_provider="ollama", ollama_character_model="m", ollama_base_url="http://gpu-box.lan:11434/v1")
    assert build_analyzer(settings(**base)).configured is False
    remote = settings(**base, ollama_allow_remote=True)
    assert build_analyzer(remote).configured is True
    # The opt-in never accepts credentials in the URL.
    assert not ollama_endpoint_ok(settings(**{**base, "ollama_base_url": "http://u:p@gpu-box.lan/v1"},
                                           ollama_allow_remote=True))
    info = provider_info(remote)
    assert info["external"] is True and info["local"] is False and "NOT on the same computer" in info["disclosure"][0]
    local = settings(ai_provider="ollama", ollama_character_model="m")
    assert consent_version(local) == "2026-10-v3-ollama" and consent_version(remote) == "2026-10-v3-ollama-remote"


def test_local_disclosure_is_accurate_about_what_is_and_is_not_local() -> None:
    info = provider_info(settings(ai_provider="ollama"))
    text = " ".join(info["disclosure"])
    assert info["id"] == "ollama" and info["local"] is True and info["external"] is False
    assert info["development_only"] is False and "fictional" not in text.lower()
    assert "on the computer that runs Madhuora's server" in text
    assert "Supabase" in text and "saved in your Madhuora database" in text and "not entirely local" in text
    assert "NVIDIA" not in text and active_provider(settings(ai_provider="ollama")) == "ollama"


# ---- request shape ----------------------------------------------------------------------------------------------

@pytest.mark.anyio
async def test_request_goes_to_the_local_openai_endpoint_without_any_credential() -> None:
    seen: dict[str, object] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"], seen["headers"], seen["body"] = str(req.url), dict(req.headers), json.loads(req.content)
        return body_for({"core_traits": [item("Remembers birthdays")]})

    r = await ollama(handler).analyze(RICH)
    body = seen["body"]
    assert isinstance(body, dict) and isinstance(seen["headers"], dict)
    assert seen["url"] == "http://localhost:11434/v1/chat/completions"
    assert "authorization" not in seen["headers"]
    assert body["model"] == "qwen-test:9b" and body["stream"] is False and body["max_tokens"] == 1024
    assert body["response_format"]["type"] == "json_schema" and body["response_format"]["json_schema"]["schema"] == OUTPUT_JSON_SCHEMA
    assert body["reasoning_effort"] == "none"
    assert "JSON Schema" in body["messages"][0]["content"] and RICH in body["messages"][1]["content"]
    assert r.provider == "ollama" and r.profile.core_traits[0].text == "Remembers birthdays"


@pytest.mark.anyio
async def test_json_mode_and_reasoning_effort_are_configurable() -> None:
    seen: dict[str, object] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(req.content)
        return body_for({})

    await ollama(handler, json_mode="prompt", reasoning_effort="").analyze(RICH)
    assert isinstance(seen["body"], dict) and "response_format" not in seen["body"] and "reasoning_effort" not in seen["body"]


@pytest.mark.anyio
async def test_a_blocked_endpoint_is_never_called() -> None:
    calls: list[str] = []
    a = OllamaAnalyzer("http://evil.example/v1", "m", 5, 512, allowed=False,
                       transport=httpx.MockTransport(lambda r: calls.append(str(r.url)) or body_for({})))
    assert a.configured is False and calls == []


# ---- honest, specific errors; one attempt; no fallback -----------------------------------------------------------

@pytest.mark.anyio
async def test_server_not_running_is_reported_as_such_after_one_attempt() -> None:
    calls = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("connection refused", request=req)

    with pytest.raises(AnalysisError) as e:
        await ollama(handler).analyze(RICH)
    assert e.value.code == "local_unavailable" and e.value.status_code == 503 and calls == 1
    assert "Ollama" in e.value.message and "sample" not in e.value.message.lower()


@pytest.mark.anyio
async def test_a_model_that_is_not_installed_is_reported_as_such() -> None:
    h = lambda _: httpx.Response(404, json={"error": {"message": "model 'qwen-test:9b' not found"}})  # noqa: E731
    with pytest.raises(AnalysisError) as e:
        await ollama(h).analyze(RICH)
    assert e.value.code == "local_model_missing" and e.value.status_code == 503


@pytest.mark.anyio
async def test_other_rejections_stay_provider_rejected_and_timeouts_are_not_retried() -> None:
    with pytest.raises(AnalysisError) as e:
        await ollama(lambda _: httpx.Response(400, json={"error": {"message": "invalid response_format"}})).analyze(RICH)
    assert e.value.code == "provider_rejected"
    n = 0

    def slow(req: httpx.Request) -> httpx.Response:
        nonlocal n
        n += 1
        raise httpx.ReadTimeout("slow", request=req)

    with pytest.raises(AnalysisError) as t:
        await ollama(slow).analyze(RICH)
    assert t.value.code == "timeout" and n == 1


@pytest.mark.anyio
async def test_a_prompt_the_server_silently_cut_short_is_rejected() -> None:
    # ~13,000 characters were sent but the server says it only read 300 tokens: its context window is too small.
    with pytest.raises(AnalysisError) as e:
        await ollama(lambda _: body_for({}, {"prompt_tokens": 300, "completion_tokens": 50})).analyze(RICH)
    assert e.value.code == "context_too_small"


@pytest.mark.anyio
async def test_truncated_and_malformed_local_output_is_rejected_like_every_provider() -> None:
    cut = lambda _: httpx.Response(200, json={"choices": [{"finish_reason": "length", "message": {"content": "{"}}],  # noqa: E731
                                              "usage": {"prompt_tokens": 4000}})
    with pytest.raises(AnalysisError) as e:
        await ollama(cut).analyze(RICH)
    assert e.value.code == "truncated"
    bad = lambda _: httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": "no json"}}],  # noqa: E731
                                              "usage": {"prompt_tokens": 4000}})
    with pytest.raises(AnalysisError) as m:
        await ollama(bad).analyze(RICH)
    assert m.value.code in ("not_json", "schema_invalid")


# ---- the shared pipeline still protects the saved profile -------------------------------------------------------------

@pytest.mark.anyio
async def test_local_output_goes_through_grounding_and_deduplication() -> None:
    same = item("Teases her closest friends constantly")
    r = await ollama(lambda _: body_for({
        "typical_expressions": ["She says something she never said"],            # not in the description
        "warmth_and_expressiveness": [same], "relationships_and_social": [same],  # identical, two sections
        "core_traits": [item("Remembers everyone's birthdays")],
    })).analyze(RICH)
    assert r.profile.typical_expressions == [] and r.profile.relationships_and_social == []
    assert r.adjustments["expressions_dropped"] == 1 and r.adjustments["exact_duplicates"] == 1


@pytest.mark.anyio
async def test_the_result_depends_on_the_submitted_description_not_a_fixed_profile() -> None:
    def echo(req: httpx.Request) -> httpx.Response:
        text = json.loads(req.content)["messages"][1]["content"]
        return body_for({"core_traits": [item("Likes tea" if "tea" in text else "Likes coffee")]})

    a, b = ollama(echo), ollama(echo)
    one = await a.analyze("He likes tea and talks slowly, in a calm and patient way with everyone he meets daily.")
    two = await b.analyze("He likes coffee and talks quickly, in an excited and eager way with everyone he meets.")
    assert one.profile.core_traits[0].text != two.profile.core_traits[0].text


# ---- routes: consent, provider switch, failure keeps the last profile ------------------------------------------------

@pytest.fixture
def ollama_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_CHARACTER_MODEL", "qwen-test:9b")
    get_settings.cache_clear()
    _in_flight.clear()
    app.dependency_overrides.pop(get_analyzer, None)


def test_analysis_needs_the_ollama_specific_consent_and_stores_the_provider(
        client: TestClient, ollama_mode: None, monkeypatch: pytest.MonkeyPatch) -> None:
    h = start(client)                                   # consents to the *ollama* version
    app.dependency_overrides[get_analyzer] = lambda: ollama(lambda _: body_for({"core_traits": [item("Warm")]}))
    r = client.post("/api/v1/twin/character/analyze", json={"version": 1}, headers=h)
    assert r.status_code == 200
    assert r.json()["character"]["generated_by"] == {"provider": "ollama", "model": "qwen-test:9b", "is_sample": False}
    # Switching to NVIDIA makes the Ollama agreement void: consent is required again, the profile stays visible.
    monkeypatch.setenv("AI_PROVIDER", "nvidia")
    get_settings.cache_clear()
    me = client.get("/api/v1/me", headers=h).json()
    assert me["ai_consent"]["granted"] is False and me["character"]["generated_by"]["provider"] == "ollama"
    app.dependency_overrides.pop(get_analyzer, None)
    assert client.post("/api/v1/twin/character/analyze", json={"version": 1}, headers=h).status_code == 403


def test_ollama_down_keeps_the_last_profile_and_never_falls_back(client: TestClient, ollama_mode: None) -> None:
    h = start(client)
    app.dependency_overrides[get_analyzer] = lambda: ollama(lambda _: body_for({"core_traits": [item("Warm")]}))
    assert client.post("/api/v1/twin/character/analyze", json={"version": 1}, headers=h).status_code == 200
    before = client.get("/api/v1/me", headers=h).json()["character"]["profile"]
    client.put("/api/v1/twin/character", json={"description": RICH, "base_version": 1}, headers=h)

    def down(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=req)

    app.dependency_overrides[get_analyzer] = lambda: ollama(down)
    r = client.post("/api/v1/twin/character/analyze", json={"version": 2}, headers=h)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "local_unavailable"
    me = client.get("/api/v1/me", headers=h).json()
    assert me["character"]["profile"] == before and me["character"]["failure"] == "local_unavailable"
    assert me["character"]["status"] == "outdated" and me["twin"]["character_description"] == RICH


def test_not_configured_ollama_is_an_honest_error_not_a_sample(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PROVIDER", "ollama")            # no model named
    get_settings.cache_clear()
    _in_flight.clear()
    app.dependency_overrides.pop(get_analyzer, None)
    h = start(client)
    r = client.post("/api/v1/twin/character/analyze", json={"version": 1}, headers=h)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "not_configured"
    assert client.get("/api/v1/me", headers=h).json()["character"]["profile"] is None


def test_ready_reports_ollama_and_warns_about_a_non_local_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_CHARACTER_MODEL", "qwen-test:9b")
    get_settings.cache_clear()
    body = TestClient(create_app()).get("/ready").json()
    assert body["ai_provider"] == "ollama" and body["configured"]["ai"] is True and body["warnings"] == []
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://example.com/v1")
    get_settings.cache_clear()
    body = TestClient(create_app()).get("/ready").json()
    assert body["configured"]["ai"] is False and any("OLLAMA_BASE_URL" in w for w in body["warnings"])


# ---- diagnosing "the AI returned something unusable": each cause has its own code and a content-free detail ----------

def chat(content: object, finish: str = "stop", **msg: object) -> httpx.Response:
    return httpx.Response(200, json={"model": "qwen-test:9b", "choices": [
        {"finish_reason": finish, "message": {"content": content, **msg}}], "usage": {"prompt_tokens": 4000, "completion_tokens": 50}})


PRIVATE_TEXT = "Meera hides her anxiety behind jokes"  # stands in for private text the diagnostics must never contain


@pytest.mark.anyio
@pytest.mark.parametrize(("response", "code"), [
    (lambda: chat(""), "empty_response"),
    (lambda: chat("<think>reasoning only</think>"), "empty_response"),
    (lambda: chat(None, reasoning="all the answer ended up in a reasoning field"), "empty_response"),
    (lambda: chat(f"Sure! Here is the profile: {PRIVATE_TEXT}"), "not_json"),
    (lambda: chat(json.dumps({"summary": PRIVATE_TEXT, "unexpected": 1})), "schema_invalid"),
    (lambda: chat(json.dumps({"summary": 7})), "schema_invalid"),
])
async def test_each_unusable_answer_has_its_own_code_and_a_content_free_detail(response, code) -> None:  # type: ignore[no-untyped-def]
    a = ollama(lambda _: response())
    with pytest.raises(AnalysisError) as e:
        await a.analyze(RICH)
    assert e.value.code == code
    assert PRIVATE_TEXT not in (e.value.detail or "") and PRIVATE_TEXT not in e.value.message
    assert RICH[:40] not in (e.value.detail or "")


def test_a_failed_analysis_is_logged_without_any_text_and_the_description_and_profile_survive(
        client: TestClient, ollama_mode: None, caplog: pytest.LogCaptureFixture) -> None:
    import logging

    h = start(client)
    app.dependency_overrides[get_analyzer] = lambda: ollama(lambda _: body_for({"core_traits": [item("Warm")]}))
    assert client.post("/api/v1/twin/character/analyze", json={"version": 1}, headers=h).status_code == 200
    before = client.get("/api/v1/me", headers=h).json()["character"]["profile"]
    client.put("/api/v1/twin/character", json={"description": RICH, "base_version": 1}, headers=h)
    app.dependency_overrides[get_analyzer] = lambda: ollama(lambda _: chat(f"not json {PRIVATE_TEXT}"))
    with caplog.at_level(logging.WARNING, logger="madhuora.character"):
        r = client.post("/api/v1/twin/character/analyze", json={"version": 2}, headers=h)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "not_json"
    logged = " ".join(rec.getMessage() for rec in caplog.records)
    assert "code=not_json" in logged and "provider=ollama" in logged
    assert PRIVATE_TEXT not in logged and RICH[:40] not in logged
    me = client.get("/api/v1/me", headers=h).json()
    assert me["character"]["profile"] == before and me["character"]["status"] == "outdated"
    assert me["character"]["failure"] == "not_json" and me["twin"]["character_description"] == RICH


def test_consent_given_for_another_provider_is_outdated_and_agreeing_again_unblocks_analysis(
        client: TestClient, ollama_mode: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """The reported pair of messages: a consent from before the switch to Ollama, plus an old stored failure."""
    monkeypatch.setenv("AI_PROVIDER", "nvidia")
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    monkeypatch.setenv("NVIDIA_CHARACTER_MODEL", "m")
    get_settings.cache_clear()
    h = start(client)                                       # agrees to the NVIDIA wording
    app.dependency_overrides[get_analyzer] = lambda: ollama(lambda _: chat("garbage"))
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    get_settings.cache_clear()
    me = client.get("/api/v1/me", headers=h).json()
    c = me["ai_consent"]
    assert c["granted"] is False and c["version"] == "2026-10-v3-nvidia" and c["current_version"] == "2026-10-v3-ollama"
    r = client.post("/api/v1/twin/character/analyze", json={"version": 1}, headers=h)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "consent_required"
    # The old wording cannot be agreed to under the new provider; the new one can, and /me reflects it at once.
    assert client.post("/api/v1/consents/ai-processing", json={"version": "2026-10-v3-nvidia"}, headers=h).status_code == 409
    assert client.post("/api/v1/consents/ai-processing", json={"version": c["current_version"]}, headers=h).status_code == 201
    c2 = client.get("/api/v1/me", headers=h).json()["ai_consent"]
    assert c2["granted"] is True and c2["version"] == "2026-10-v3-ollama"
    r = client.post("/api/v1/twin/character/analyze", json={"version": 1}, headers=h)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "not_json"   # now it reaches the model (and fails honestly)
