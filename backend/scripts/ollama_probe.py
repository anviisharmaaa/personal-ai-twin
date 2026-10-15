"""Find out EXACTLY where a local Ollama answer fails, using only the FICTIONAL smoke description. Local only.

    python -m scripts.ollama_probe

Tries the four request shapes (json_schema or prompt-only JSON, with and without reasoning_effort) against your
configured OLLAMA_BASE_URL / OLLAMA_CHARACTER_MODEL and reports for each: HTTP status, finish reason, token counts,
whether the text came back in `content` or in a reasoning field, and which stage accepts or rejects it
(HTTP -> content -> JSON -> schema -> grounding). It never uses your own descriptions and never contacts a cloud service.
"""
from __future__ import annotations

import asyncio
import sys
import time

import httpx

from app.character import AnalysisError, _unwrap, parse_profile
from app.config import get_settings
from app.grounding import ground
from app.providers import OllamaAnalyzer, ollama_endpoint_ok
from scripts.live_character_smoke import SMOKE


async def probe(mode: str, effort: str, s) -> bool:  # type: ignore[no-untyped-def]
    a = OllamaAnalyzer(s.ollama_base_url, s.ollama_character_model, s.ollama_timeout_seconds,
                       s.ollama_max_output_tokens, json_mode=mode, reasoning_effort=effort)
    payload = a._payload(SMOKE)
    t = time.monotonic()
    print(f"\n== json_mode={mode} reasoning_effort={effort or '(not sent)'}")
    try:
        async with httpx.AsyncClient(timeout=s.ollama_timeout_seconds) as c:
            res = await c.post(s.ollama_base_url.rstrip("/") + "/chat/completions", json=payload)
    except httpx.HTTPError as exc:
        print(f"   NETWORK: {type(exc).__name__} (is `ollama serve` running?)")
        return False
    took = time.monotonic() - t
    if res.status_code != 200:
        print(f"   HTTP {res.status_code}: {res.text[:300]}")
        return False
    data = res.json()
    ch = data["choices"][0]
    msg = ch["message"]
    content = msg.get("content")
    reasoning = msg.get("reasoning") or msg.get("reasoning_content")
    u = data.get("usage") or {}
    print(f"   HTTP 200 in {took:.1f}s finish={ch.get('finish_reason')} prompt_tokens={u.get('prompt_tokens')} "
          f"completion_tokens={u.get('completion_tokens')} content_chars={len(content or '')} "
          f"reasoning_field={'yes, ' + str(len(reasoning)) + ' chars' if reasoning else 'no'}")
    if ch.get("finish_reason") == "length":
        print("   STOP: output cut off at the token limit -> raise OLLAMA_MAX_OUTPUT_TOKENS, or reasoning is eating it.")
        return False
    try:
        prof = parse_profile(content or "")
    except AnalysisError as e:
        print(f"   REJECTED at parse: {e.code} - {e.detail}")
        print(f"   first 300 chars of the (fictional) reply: {_unwrap(content or '')[:300]!r}")
        return False
    print("   JSON and schema: OK")
    try:
        final, adj = ground(prof, SMOKE)
        print(f"   Grounding: OK, kept entries, fixes={adj.as_dict()}")
        return True
    except AnalysisError as e:
        print(f"   REJECTED at grounding: {e.code} - {e.detail}")
        return False


async def main() -> int:
    s = get_settings()
    if s.ai_provider.strip().lower() != "ollama" or not s.ollama_character_model or not ollama_endpoint_ok(s):
        print("Set AI_PROVIDER=ollama and OLLAMA_CHARACTER_MODEL in backend/.env (local address only).")
        return 2
    print(f"Probing {s.ollama_character_model} at {s.ollama_base_url} with the FICTIONAL smoke text (local only).")
    ok = [await probe(m, e, s) for m, e in (("schema", "none"), ("schema", ""), ("prompt", "none"), ("prompt", ""))]
    print("\nSUMMARY: working shapes ->", [i for i, v in enumerate(ok) if v] or "none")
    print("Shapes: 0=schema+reasoning none, 1=schema, 2=prompt+reasoning none, 3=prompt. Set OLLAMA_JSON_MODE / "
          "OLLAMA_REASONING_EFFORT in backend/.env to the first working shape.")
    return 0 if any(ok) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
