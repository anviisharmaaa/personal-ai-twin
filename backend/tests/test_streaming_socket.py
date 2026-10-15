"""Real sockets, simulated model. Madhuora's real ASGI app is served by uvicorn, and a stub 'Ollama' server (not a
model) emits its stream slowly with a multi-byte character split across network writes. The test measures when each
piece reaches the HTTP client, which proves the backend does not buffer the reply; it says NOTHING about real Ollama
or real model speed (use scripts/live_chat_smoke.py for that)."""
import asyncio
import json
import socket
import threading
import time
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.responses import StreamingResponse
from starlette.routing import Route

from app.config import get_settings
from app.main import app
from tests.test_chat import _reset, new_conversation, parse_sse, ready_user  # noqa: F401 - _reset is an autouse fixture


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _serve(asgi: object, port: int) -> tuple[uvicorn.Server, threading.Thread]:
    server = uvicorn.Server(uvicorn.Config(asgi, host="127.0.0.1", port=port, log_level="error"))  # type: ignore[arg-type]
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            return server, t
        time.sleep(0.05)
    raise RuntimeError("server did not start")


def _stub_ollama() -> Starlette:
    async def completions(request: object) -> StreamingResponse:
        def chunk(obj: dict[str, object]) -> bytes:
            return b"data: " + json.dumps(obj, ensure_ascii=False).encode() + b"\n\n"

        async def gen() -> AsyncIterator[bytes]:
            await asyncio.sleep(0.3)                                    # "thinking" before the first word
            for word in ("Namaste ", "दोस्त ", "kaise ", "ho?"):
                b = chunk({"choices": [{"delta": {"content": word}}]})
                mid = len(b) // 2 + 1
                yield b[:mid]                                           # may cut a UTF-8 character in half
                await asyncio.sleep(0.05)
                yield b[mid:]
                await asyncio.sleep(0.3)
            usage = {"prompt_tokens": 2000, "completion_tokens": 8}
            yield chunk({"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": usage})
            yield b"data: [DONE]\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")
    return Starlette(routes=[Route("/v1/chat/completions", completions, methods=["POST"])])


@pytest.fixture
def servers(monkeypatch: pytest.MonkeyPatch) -> Iterator[int]:
    ollama_port, app_port = _free_port(), _free_port()
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_CHARACTER_MODEL", "stub:1b")
    monkeypatch.setenv("OLLAMA_BASE_URL", f"http://127.0.0.1:{ollama_port}/v1")
    get_settings.cache_clear()
    s1, t1 = _serve(_stub_ollama(), ollama_port)
    s2, t2 = _serve(app, app_port)
    yield app_port
    s1.should_exit = s2.should_exit = True
    t1.join(5)
    t2.join(5)


def test_the_reply_reaches_the_client_piece_by_piece_through_the_real_stack(client, fake, servers: int) -> None:  # type: ignore[no-untyped-def]
    h = ready_user(client, fake)
    cid = new_conversation(client, h)
    t0 = time.perf_counter()
    stamps: list[float] = []
    buf = b""
    with httpx.stream("POST", f"http://127.0.0.1:{servers}/api/v1/conversations/{cid}/messages/stream", headers=h,
                      json={"content": "Namaste", "client_message_id": "sock-test-0001"}, timeout=20) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        for part in r.iter_bytes():
            buf += part
            while b"\n\n" in buf:
                frame, buf = buf.split(b"\n\n", 1)
                if b"event: delta" in frame:
                    stamps.append(time.perf_counter() - t0)
                if b"event: done" in frame:
                    stamps.append(-1.0)
    deltas = [x for x in stamps if x >= 0]
    assert len(deltas) == 4 and stamps[-1] == -1.0
    assert deltas[0] > 0.25                                        # nothing is invented before the model's first word
    assert deltas[-1] - deltas[0] > 0.7                            # pieces arrived over time, not as one block
    assert all(b - a > 0.15 for a, b in zip(deltas, deltas[1:], strict=False))
    msgs = client.get(f"/api/v1/conversations/{cid}/messages", headers=h).json()["messages"]
    assert msgs[1]["content"] == "Namaste दोस्त kaise ho?" and msgs[1]["status"] == "complete"
    assert msgs[1]["first_token_ms"] is not None and msgs[1]["first_token_ms"] >= 250


def test_closing_the_connection_early_saves_a_stopped_reply_and_frees_the_model(client, fake, servers: int) -> None:  # type: ignore[no-untyped-def]
    from app.chat import model_gate
    from app.conversation_routes import _streaming
    h = ready_user(client, fake)
    cid = new_conversation(client, h)
    with httpx.stream("POST", f"http://127.0.0.1:{servers}/api/v1/conversations/{cid}/messages/stream", headers=h,
                      json={"content": "Namaste", "client_message_id": "sock-test-0002"}, timeout=20) as r:
        seen = b""
        for part in r.iter_bytes():
            seen += part
            if b"event: delta" in seen:
                break                                              # the user pressed Stop after the first word
    for _ in range(60):
        rows = [m for m in fake.tables["messages"] if m["role"] == "assistant"]
        if rows and rows[0]["status"] != "streaming" and not model_gate.busy and cid not in _streaming:
            break
        time.sleep(0.1)
    a = [m for m in fake.tables["messages"] if m["role"] == "assistant"][0]
    assert a["status"] == "cancelled" and a["content"].startswith("Namaste") and a["status"] != "complete"
    assert model_gate.busy is False and cid not in _streaming
    # and the very next message works (nothing is stuck)
    ev = parse_sse(httpx.post(f"http://127.0.0.1:{servers}/api/v1/conversations/{cid}/messages/stream", headers=h,
                              json={"content": "Again", "client_message_id": "sock-test-0003"}, timeout=30).text)
    assert ev[-1][0] == "done"
