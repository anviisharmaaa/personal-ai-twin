# ruff: noqa: E501, F811
"""NVIDIA Nemotron chat provider. MOCKED: the HTTP layer is httpx.MockTransport, so nothing here is evidence that a real
NVIDIA request works. The user-run `scripts/live_nvidia_chat_smoke.py` is the only live check (docs/LIVE_VERIFICATION.md)."""
import asyncio
import json
import logging
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.chat import ChatError, ChatMessage, NvidiaChatProvider, UnavailableChat, build_chat_provider, model_gate
from app.config import Settings, get_settings
from app.providers import active_chat_provider, chat_disclosure, consent_version
from tests.fake_supabase import FakeSupabase
from tests.test_chat import _reset, new_conversation, parse_sse, ready_user, send, use  # noqa: F401
from tests.test_gender import NEUTRAL, convo, made

KEY = "nvapi-TEST-SENTINEL-KEY-0123456789"
URL = "https://integrate.api.nvidia.com/v1"
MODEL = "nvidia/nemotron-3-ultra-550b-a55b"
MSGS = [ChatMessage("system", "You are a character."), ChatMessage("user", "hi")]


def sse_body(*events: Any) -> bytes:
    out = ""
    for e in events:
        out += f"data: {e if isinstance(e, str) else json.dumps(e)}\n\n"
    return out.encode()


def chunk(text: str | None = None, finish: str | None = None, **delta: Any) -> dict[str, Any]:
    d = dict(delta)
    if text is not None:
        d["content"] = text
    return {"choices": [{"index": 0, "delta": d, "finish_reason": finish}]}


class Nv:
    """A real NvidiaChatProvider whose HTTP layer records requests and replays a scripted response."""

    def __init__(self, body: bytes | None = None, status: int = 200, exc: Exception | None = None, **kw: Any) -> None:
        self.requests: list[httpx.Request] = []
        self._body = body if body is not None else sse_body(chunk("Hi "), chunk("there."), chunk(None, "stop"), "[DONE]")
        self._status, self._exc = status, exc
        self.provider = NvidiaChatProvider(URL, MODEL, KEY, max_output_tokens=kw.pop("max_output_tokens", 128),
                                           first_token_timeout=5, total_timeout=30,
                                           transport=httpx.MockTransport(self._handle), **kw)

    def _handle(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        if self._exc:
            raise self._exc
        return httpx.Response(self._status, content=self._body, headers={"content-type": "text/event-stream"})

    @property
    def body(self) -> dict[str, Any]:
        return json.loads(self.requests[-1].content)


async def collect(p: NvidiaChatProvider) -> tuple[list[str], Any]:
    deltas, meta = [], None
    async for kind, val in p.stream(MSGS):
        if kind == "delta":
            deltas.append(val)
        else:
            meta = val
    return deltas, meta


def run_err(p: NvidiaChatProvider) -> ChatError:
    with pytest.raises(ChatError) as ei:
        asyncio.run(collect(p))
    return ei.value


@pytest.fixture
def nvidia_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHAT_PROVIDER", "nvidia")
    monkeypatch.setenv("NVIDIA_API_KEY", KEY)
    get_settings.cache_clear()


# ---- request ----------------------------------------------------------------------------------------------------------

def test_request_goes_to_chat_completions_with_bearer_key_and_documented_parameters() -> None:
    nv = Nv()
    asyncio.run(collect(nv.provider))
    req = nv.requests[0]
    assert str(req.url) == f"{URL}/chat/completions" and req.method == "POST"
    assert req.headers["authorization"] == f"Bearer {KEY}"
    b = nv.body
    assert b["model"] == MODEL and b["stream"] is True and b["max_tokens"] == 128
    assert b["chat_template_kwargs"] == {"enable_thinking": False}
    assert b["messages"] == [{"role": "system", "content": "You are a character."}, {"role": "user", "content": "hi"}]


def test_settings_default_to_nvidia_nemotron_and_reuse_the_existing_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CHAT_PROVIDER")        # the test fixtures switch chat off; this checks the real default
    s = Settings(_env_file=None, nvidia_api_key=KEY)       # type: ignore[call-arg]
    assert s.chat_provider == "nvidia" and s.nvidia_chat_model == MODEL and s.nvidia_base_url == URL
    assert s.chat_max_output_tokens == 128
    p = build_chat_provider(s)
    assert isinstance(p, NvidiaChatProvider) and p.configured and p.model == MODEL and p.exclusive is False
    assert KEY not in json.dumps(p.settings_summary()) and p.settings_summary()["enable_thinking"] is False


def test_the_output_limit_is_chat_max_output_tokens() -> None:
    p = build_chat_provider(Settings(_env_file=None, chat_provider="nvidia", nvidia_api_key=KEY, chat_max_output_tokens=200))   # type: ignore[call-arg]
    assert isinstance(p, NvidiaChatProvider) and p.settings_summary()["max_tokens"] == 200


def test_chat_provider_is_independent_of_ai_provider() -> None:
    for ai in ("", "ollama", "openai", "mock", "nvidia"):
        s = Settings(_env_file=None, chat_provider="nvidia", ai_provider=ai, nvidia_api_key=KEY, openai_api_key="k", ollama_character_model="m")   # type: ignore[call-arg]
        assert isinstance(build_chat_provider(s), NvidiaChatProvider) and active_chat_provider(s) == "nvidia"


def test_missing_key_or_insecure_url_is_not_configured_never_a_fallback() -> None:
    for kw in ({}, {"nvidia_api_key": "   "}, {"nvidia_api_key": KEY, "nvidia_base_url": "http://integrate.api.nvidia.com/v1"},
               {"nvidia_api_key": KEY, "nvidia_chat_model": " "}):
        c = build_chat_provider(Settings(_env_file=None, chat_provider="nvidia", ollama_character_model="m", ai_provider="ollama", **kw))   # type: ignore[call-arg]
        assert isinstance(c, UnavailableChat) and c.code == "not_configured" and not c.configured and c.provider == "nvidia"


def test_mock_chat_is_refused_in_production() -> None:
    assert active_chat_provider(Settings(_env_file=None, chat_provider="mock", app_env="production")) == ""   # type: ignore[call-arg]


# ---- streaming --------------------------------------------------------------------------------------------------------

def test_deltas_arrive_one_per_event_in_order_and_finish_reason_is_reported() -> None:
    nv = Nv(sse_body(chunk(role="assistant"), chunk("Na"), chunk("maste "), chunk("नमस्ते"), chunk(None, "stop"),
                     {"usage": {"prompt_tokens": 50, "completion_tokens": 4}, "choices": []}, "[DONE]"))
    deltas, meta = asyncio.run(collect(nv.provider))
    assert deltas == ["Na", "maste ", "नमस्ते"]
    assert meta.finish_reason == "stop" and meta.prompt_tokens == 50 and meta.completion_tokens == 4
    assert meta.first_token_ms is not None and meta.duration_ms is not None


def test_reasoning_content_is_ignored_never_yielded() -> None:
    nv = Nv(sse_body(chunk(None, reasoning_content="secret chain of thought"), chunk(None, reasoning="more"),
                     chunk("Visible."), chunk(None, "stop"), "[DONE]"))
    deltas, meta = asyncio.run(collect(nv.provider))
    assert deltas == ["Visible."] and meta.thinking_chars == len("secret chain of thought") + len("more")


def test_inline_think_tags_are_filtered() -> None:
    nv = Nv(sse_body(chunk("<think>hidden</think>Hello"), chunk(None, "stop"), "[DONE]"))
    deltas, _ = asyncio.run(collect(nv.provider))
    assert "".join(deltas) == "Hello"


def test_length_finish_is_reported_so_the_reply_is_stored_incomplete() -> None:
    _, meta = asyncio.run(collect(Nv(sse_body(chunk("cut o"), chunk(None, "length"), "[DONE]")).provider))
    assert meta.finish_reason == "length"


def test_comments_and_blank_lines_are_skipped_and_garbage_is_an_error() -> None:
    ok = Nv(b": keep-alive\n\n" + sse_body(chunk("A"), "[DONE]"))
    assert asyncio.run(collect(ok.provider))[0] == ["A"]
    assert run_err(Nv(b"data: {not json\n\n").provider).code == "invalid_stream"
    assert run_err(Nv(sse_body({"error": {"message": f"boom {KEY}"}}, "[DONE]")).provider).code == "provider_error"


# ---- errors: clear, actionable, key never leaked, no fallback ---------------------------------------------------------

@pytest.mark.parametrize(("status", "code", "hint"), [
    (401, "provider_auth", "NVIDIA_API_KEY"), (403, "provider_auth", "NVIDIA_API_KEY"),
    (429, "provider_rate_limited", "rate limiting"), (404, "provider_model_missing", "NVIDIA_CHAT_MODEL"),
    (500, "provider_unavailable", "unavailable"), (502, "provider_unavailable", "unavailable"),
    (503, "provider_unavailable", "unavailable"), (400, "provider_rejected", "couldn't accept"),
])
def test_http_errors_map_to_clear_codes_and_never_echo_the_key_or_the_response(status: int, code: str, hint: str) -> None:
    nv = Nv(json.dumps({"detail": f"echo {KEY} and user text"}).encode(), status=status)
    err = run_err(nv.provider)
    assert err.code == code and hint in err.message
    assert KEY not in err.message and KEY not in (err.detail or "") and "user text" not in (err.detail or "")
    assert len(nv.requests) == 1       # one attempt: no retry against another model or provider


def test_timeouts_and_connection_failures_have_their_own_codes() -> None:
    assert run_err(Nv(exc=httpx.ConnectTimeout("t")).provider).code == "provider_unreachable"
    assert run_err(Nv(exc=httpx.ConnectError("c")).provider).code == "provider_unreachable"
    assert run_err(Nv(exc=httpx.ReadTimeout("r")).provider).code == "first_token_timeout"
    assert run_err(Nv(exc=httpx.RemoteProtocolError("p")).provider).code == "interrupted"


# ---- consent and disclosure -------------------------------------------------------------------------------------------

def test_consent_version_changes_with_the_chat_provider_and_discloses_nvidia() -> None:
    off = Settings(_env_file=None, chat_provider="")          # type: ignore[call-arg]
    nv = Settings(_env_file=None, chat_provider="nvidia")     # type: ignore[call-arg]
    assert consent_version(off) == "2026-10-v3-none" and consent_version(nv) == "2026-10-v3-none-chat-nvidia"
    d = chat_disclosure(nv)
    text = " ".join(d["disclosure"])
    assert d["external"] is True and d["development_only"] is True
    assert "trial" in text.lower() and "pronouns" in text and "memories" in text and "NVIDIA" in text


# ---- through the API: persistence, isolation, no gate, no leakage -----------------------------------------------------

def test_streamed_reply_is_persisted_complete_and_does_not_use_the_local_model_gate(
        client: TestClient, fake: FakeSupabase, nvidia_env: None, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    h = ready_user(client, fake)
    cid = new_conversation(client, h)
    nv = Nv()
    use(nv.provider)
    assert model_gate.try_acquire()                 # a local job holds the slot; NVIDIA chat must not wait for it
    r = send(client, h, cid, "Hello there")
    assert r.status_code == 200
    ev = parse_sse(r.text)
    assert [e for e, _ in ev] == ["started", "delta", "delta", "done"]
    assert "".join(d["text"] for k, d in ev if k == "delta") == "Hi there."
    msgs = client.get(f"/api/v1/conversations/{cid}/messages", headers=h).json()["messages"]
    asst = [m for m in msgs if m["role"] == "assistant"][-1]
    assert asst["content"] == "Hi there." and asst["status"] == "complete" and asst["provider"] == "nvidia" and asst["model"] == MODEL
    status = client.get("/api/v1/chat/status", headers=h).json()
    assert status["available"] is True and status["provider"] == "nvidia" and status["model_busy"] is False
    blob = r.text + json.dumps(msgs) + json.dumps(status) + caplog.text
    assert KEY not in blob and "Hello there" not in caplog.text


def test_an_nvidia_failure_is_saved_as_failed_with_its_code_and_nothing_falls_back(
        client: TestClient, fake: FakeSupabase, nvidia_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_CHARACTER_MODEL", "would-be-fallback")
    get_settings.cache_clear()
    h = ready_user(client, fake)
    cid = new_conversation(client, h)
    nv = Nv(b"{}", status=401)
    use(nv.provider)
    ev = parse_sse(send(client, h, cid, "hi").text)
    assert ev[-1][0] == "error" and ev[-1][1]["code"] == "provider_auth" and KEY not in json.dumps(ev)
    msgs = client.get(f"/api/v1/conversations/{cid}/messages", headers=h).json()["messages"]
    asst = [m for m in msgs if m["role"] == "assistant"][-1]
    assert asst["status"] == "failed" and asst["failure_code"] == "provider_auth" and len(nv.requests) == 1
    assert [m["role"] for m in msgs].count("user") == 1       # the user's message is kept


def test_rate_limit_is_reported_to_the_browser_with_its_code(
        client: TestClient, fake: FakeSupabase, nvidia_env: None) -> None:
    h = ready_user(client, fake)
    cid = new_conversation(client, h)
    use(Nv(b"{}", status=429).provider)
    ev = parse_sse(send(client, h, cid, "hi").text)
    assert ev[-1][1]["code"] == "provider_rate_limited"


def test_retry_with_the_same_client_message_id_replays_without_a_second_nvidia_call(
        client: TestClient, fake: FakeSupabase, nvidia_env: None) -> None:
    h = ready_user(client, fake)
    cid = new_conversation(client, h)
    nv = Nv()
    use(nv.provider)
    send(client, h, cid, "once", key="key-idem-0001")
    again = send(client, h, cid, "once", key="key-idem-0001")
    assert len(nv.requests) == 1 and parse_sse(again.text)[0][1].get("replayed") is True


def test_the_request_carries_character_gender_user_identity_and_description_but_no_key(
        client: TestClient, fake: FakeSupabase, nvidia_env: None) -> None:
    h = ready_user(client, fake)
    assert client.put("/api/v1/me/profile", json={"user_gender": "man", "user_pronouns": "he/him"}, headers=h).status_code == 200
    fid = made(client, h, "Sana", NEUTRAL, gender="female")
    cid = convo(client, h, fid)
    nv = Nv()
    use(nv.provider)
    assert send(client, h, cid, "kaise ho?").status_code == 200
    system = nv.body["messages"][0]["content"]
    assert "<character_identity>" in system and "<user_identity>" in system and "female" in system and "he/him" in system
    assert NEUTRAL[:30] in system
    assert KEY not in json.dumps(nv.body) and nv.body["messages"][-1] == {"role": "user", "content": "kaise ho?"}
