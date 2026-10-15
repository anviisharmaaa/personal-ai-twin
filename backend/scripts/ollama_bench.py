"""Measure local latency and where the model runs, using ONLY synthetic (fictional) descriptions. Local only.

    python -m scripts.ollama_bench                    # configured model: load time, then short / rich / long
    python -m scripts.ollama_bench --model qwen3.5:4b # compare an INSTALLED model (never downloads anything)

Reports, per case: seconds, prompt/completion tokens, tokens per second, and which pipeline stage accepted or rejected
the result (parse -> schema -> grounding), plus the model-load time (a first tiny request) and, from Ollama's /api/ps,
how much of the model sits in GPU memory versus system RAM (a model that doesn't fit in VRAM runs partly on the CPU
and is much slower). Results contain only fictional text.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time

import httpx

from app.character import MAX_DESCRIPTION_CHARS, AnalysisError
from app.config import get_settings
from app.providers import OllamaAnalyzer, ollama_endpoint_ok
from scripts.live_character_smoke import CASES, SMOKE


def long_text() -> str:
    parts = [SMOKE, *CASES.values()]
    out = ""
    for p in parts:
        if len(out) + len(p) + 1 > MAX_DESCRIPTION_CHARS - 200:
            break
        out += p + " "
    return out.strip()


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", help="an already-installed model to measure instead of OLLAMA_CHARACTER_MODEL")
    args = ap.parse_args()
    s = get_settings()
    model = args.model or s.ollama_character_model
    if not model or not ollama_endpoint_ok(s):
        print("Set OLLAMA_CHARACTER_MODEL (or pass --model) and keep OLLAMA_BASE_URL on a local address.")
        return 2
    root = s.ollama_base_url.rstrip("/").removesuffix("/v1")
    try:
        names = [m.get("name") for m in httpx.get(root + "/api/tags", timeout=10).json().get("models", [])]
    except (httpx.HTTPError, ValueError):
        print("Ollama is not reachable. Start it with: ollama serve")
        return 1
    if model not in names and f"{model}:latest" not in names:
        print(f"{model!r} is not installed (installed: {names}). Nothing is downloaded automatically.")
        return 1
    print(f"Model {model}  endpoint {s.ollama_base_url}  (synthetic text only)")

    # 1. Model load time: a tiny request, so weight loading is separated from analysis time.
    t = time.monotonic()
    try:
        httpx.post(s.ollama_base_url.rstrip("/") + "/chat/completions", timeout=s.ollama_timeout_seconds,
                   json={"model": model, "messages": [{"role": "user", "content": "Reply with the word ok."}],
                         "max_tokens": 4, "stream": False})
    except httpx.HTTPError as exc:
        print(f"Warm-up failed: {type(exc).__name__}")
        return 1
    print(f"Load + tiny request: {time.monotonic() - t:.1f}s  (later requests skip the load while it stays in memory)")

    # 2. Where is it running?
    try:
        for m in httpx.get(root + "/api/ps", timeout=10).json().get("models", []):
            size, vram = m.get("size") or 0, m.get("size_vram") or 0
            where = "100% GPU" if size and vram >= size else ("CPU only" if not vram else f"{100 * vram // size}% GPU / rest CPU")
            print(f"Loaded: {m.get('name')} {size / 1e9:.1f} GB total, {vram / 1e9:.1f} GB in GPU memory -> {where}; "
                  f"context {m.get('context_length', 'unknown')}")
    except (httpx.HTTPError, ValueError):
        print("(could not read /api/ps)")

    a = OllamaAnalyzer(s.ollama_base_url, model, s.ollama_timeout_seconds, s.ollama_max_output_tokens,
                       json_mode=s.ollama_json_mode, reasoning_effort=s.ollama_reasoning_effort)
    cases = {"short": SMOKE, "rich": CASES["rich_contextual"], "long": long_text()}
    for name, text in cases.items():
        t = time.monotonic()
        try:
            r = await a.analyze(text)
        except AnalysisError as e:
            print(f"- {name:5} ({len(text)} chars): {time.monotonic() - t:6.1f}s  REJECTED {e.code}: {e.detail}")
            continue
        dt = time.monotonic() - t
        tps = (r.output_tokens or 0) / dt if dt else 0
        print(f"- {name:5} ({len(text)} chars): {dt:6.1f}s  in={r.input_tokens} out={r.output_tokens} "
              f"~{tps:.1f} tok/s  OK  kept entries after validation; fixes={r.adjustments}")
    print("Quality needs your reading: run the smoke script with --eval and read the saved output.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
