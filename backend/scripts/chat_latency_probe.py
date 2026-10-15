"""LIVE controlled latency investigation of Madhuora's real chat request path (native Ollama /api/chat). Run on your PC.

    python -m scripts.chat_latency_probe [--reps 3] [--model qwen3.5:9b] [--skip-uncached]

Invented character and messages only; your own Ollama only; no downloads, no paid calls, nothing written but the
terminal. It changes ONE thing at a time and repeats each condition, so a cause is not read from a single run.

Experiments (every call uses the production request: think=false, num_predict from CHAT_MAX_OUTPUT_TOKENS, keep_alive):

  1. MODEL PLACEMENT  /api/ps: size vs size_vram. A model that does not fit in GPU memory is partly evaluated on the CPU,
                       which makes reading the prompt (prefill) slow regardless of prompt wording.
  2. HISTORY SWEEP    0 / 6 / 12 / 24 earlier messages, same system prompt, same final user message, >= 3 repetitions,
                       condition order rotated each round (a Latin square) so "later in the run" cannot masquerade
                       as "more history". Reported: prompt tokens, first token, total, prompt-eval time, generation time,
                       output tokens, load time, and the median of each.
  3. PREFILL ONLY     the same sweep with num_predict=1: isolates prompt processing from generation.
  4. PROMPT CACHE     (a) the identical request twice in a row (cache hit expected: prompt_eval_count is then small and
                       first token fast); (b) the same request after a request with a DIFFERENT system prompt (cache miss).
                       Madhuora's normal chat repeats the same prefix, whereas an alternating benchmark does not.
  5. SYSTEM PROMPT    uncached prefill of system-prompt-only vs the whole thing, giving tokens per second of prefill.

It prints medians and a plain-language reading of what the numbers support; it does not assume a cause.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from typing import Any

import httpx

from app.chat import ChatMessage, OllamaChatProvider, ollama_native_base, system_prompt
from app.config import get_settings
from app.providers import ollama_endpoint_ok

DESC = ("Kiran is a sharp-tongued, affectionate older sister figure in her late twenties. She teases people she loves, "
        "writes casually, hates long speeches, and when someone is really upset she drops the jokes and gets quiet and "
        "gentle. She is proud of her terrible cooking and refuses to admit it.")
PADDING = [("user", "what are you up to this weekend?"), ("assistant", "laundry and bad tv, mostly."),
           ("user", "want to watch something together?"), ("assistant", "only if you pick. i always pick wrong."),
           ("user", "deal. i pick something funny"), ("assistant", "ok good. no sad movies."),
           ("user", "should we order food or cook?"), ("assistant", "order. trust me on this."),
           ("user", "fine. what do you want?"), ("assistant", "anything but my own cooking."),
           ("user", "haha fair. pizza then?"), ("assistant", "pizza. extra cheese, no arguments.")]
FINAL = "so what time should we start the movie?"
CONDITIONS = (0, 6, 12, 24)


def history(n: int) -> list[ChatMessage]:
    msgs = (PADDING * 2)[:n]
    return [ChatMessage(r, t) for r, t in msgs]


def _ms(final: dict[str, Any], key: str) -> int:
    return int(final.get(key, 0) / 1e6)


async def call(base: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    """One streamed /api/chat call; returns the numbers (never the text)."""
    t0 = time.perf_counter()
    first: float | None = None
    final: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=timeout) as c:
        async with c.stream("POST", base + "/api/chat", json=payload) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.strip():
                    continue
                o = json.loads(line)
                if (o.get("message") or {}).get("content") and first is None:
                    first = time.perf_counter() - t0
                if o.get("done"):
                    final = o
    return {"first": int((first or 0) * 1000), "total": int((time.perf_counter() - t0) * 1000),
            "ptok": final.get("prompt_eval_count"), "otok": final.get("eval_count"), "pe": _ms(final, "prompt_eval_duration"),
            "gen": _ms(final, "eval_duration"), "load": _ms(final, "load_duration")}


def med(rows: list[dict[str, Any]], k: str) -> str:
    vals = [r[k] for r in rows if isinstance(r.get(k), (int, float))]
    return f"{int(statistics.median(vals)):>6}" if vals else "     -"


def table(title: str, groups: dict[Any, list[dict[str, Any]]]) -> None:
    print(f"\n{title}")
    print("  cond | runs | prompt tok | first ms | total ms | prompt-eval ms | gen ms | out tok | load ms (max)")
    for k, rows in groups.items():
        print(f"  {str(k):>4} | {len(rows):>4} | {med(rows, 'ptok')}     | {med(rows, 'first')}   | {med(rows, 'total')}   | "
              f"{med(rows, 'pe')}         | {med(rows, 'gen')} | {med(rows, 'otok')}  | {max(r['load'] for r in rows):>6}")


async def ps(base: str) -> None:
    async with httpx.AsyncClient(timeout=10) as c:
        data = (await c.get(base + "/api/ps")).json().get("models", [])
    if not data:
        print("  /api/ps: no model loaded right now")
    for m in data:
        size, vram = m.get("size", 0), m.get("size_vram", 0)
        pct = 100 * vram / size if size else 0
        print(f"  {m.get('name')}: {size / 1e9:.1f} GB total, {vram / 1e9:.1f} GB in GPU memory ({pct:.0f}%), "
              f"context {m.get('context_length', 'n/a')}, expires {m.get('expires_at', 'n/a')}")
        if size and pct < 99:
            print("  -> part of the model runs on the CPU. Prompt reading will be slow no matter how the prompt is worded.")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--model")
    ap.add_argument("--skip-uncached", action="store_true", help="skip the cache-miss experiment")
    args = ap.parse_args()
    s = get_settings()
    model = args.model or s.ollama_character_model
    if not model or not ollama_endpoint_ok(s):
        print("Set OLLAMA_CHARACTER_MODEL (and a local OLLAMA_BASE_URL) in backend/.env first.")
        return 2
    base = ollama_native_base(s.ollama_base_url)
    prov = OllamaChatProvider(s.ollama_base_url, model, max_output_tokens=s.chat_max_output_tokens,
                              first_token_timeout=s.chat_first_token_timeout_seconds,
                              total_timeout=s.chat_total_timeout_seconds, think=s.chat_think,
                              temperature=s.chat_temperature, num_ctx=s.chat_num_ctx, keep_alive=s.chat_keep_alive)
    sysmsg = system_prompt("Kiran", None, DESC, [])
    T = s.chat_total_timeout_seconds

    def payload(n: int, *, system: str = sysmsg, predict: int | None = None, final: str = FINAL) -> dict[str, Any]:
        p = prov._payload([ChatMessage("system", system), *history(n), ChatMessage("user", final)])
        p["options"] = {**p["options"], "seed": 7}
        if predict:
            p["options"]["num_predict"] = predict
        return p

    print(f"model={model} settings={prov.settings_summary()}")
    print("\n1. MODEL PLACEMENT (after a first call so the model is loaded)")
    try:
        warm = await call(base, payload(0), T)
    except Exception as exc:  # noqa: BLE001
        print(f"Could not reach Ollama: {type(exc).__name__}. Is it running?")
        return 2
    print(f"  warm-up call: first {warm['first']} ms, total {warm['total']} ms, load {warm['load']} ms")
    await ps(base)

    full: dict[int, list[dict[str, Any]]] = {n: [] for n in CONDITIONS}
    pre: dict[int, list[dict[str, Any]]] = {n: [] for n in CONDITIONS}
    reloads = 0
    for rep in range(args.reps):
        order = CONDITIONS[rep % 4:] + CONDITIONS[:rep % 4]            # rotated: each condition meets each position
        for n in order:
            r = await call(base, payload(n), T)
            full[n].append(r)
            reloads += r["load"] > 1000
            p = await call(base, payload(n, predict=1), T)
            pre[n].append(p)
            reloads += p["load"] > 1000
        print(f"  round {rep + 1}/{args.reps} done (order {list(order)})")
    table("2. HISTORY SWEEP, production settings (medians; order rotated every round)", full)
    table("3. PREFILL ONLY (num_predict=1): prompt processing without generation", pre)
    print(f"  model (re)loads seen (load > 1 s): {reloads}")

    print("\n4. PROMPT CACHE")
    same: list[dict[str, Any]] = []
    for _ in range(args.reps):
        await call(base, payload(6, predict=1), T)                      # prime
        same.append(await call(base, payload(6, predict=1), T))         # identical request straight after
    table("   identical request repeated (cache hit expected)", {"hit": same})
    if not args.skip_uncached:
        miss: list[dict[str, Any]] = []
        for i in range(args.reps):
            await call(base, payload(6, system=f"[{i}] You are a different assistant. " + sysmsg, predict=1), T)
            miss.append(await call(base, payload(6, predict=1), T))     # after a request with another system prompt
        table("   same request right after a request with a DIFFERENT system prompt (cache miss expected)", {"miss": miss})
        if same and miss:
            h, m = statistics.median(r["first"] for r in same), statistics.median(r["first"] for r in miss)
            print(f"   -> cache hit first token {int(h)} ms vs miss {int(m)} ms")
            ph, pm = statistics.median(r["ptok"] or 0 for r in same), statistics.median(r["ptok"] or 0 for r in miss)
            if pm and ph < 0.5 * pm:
                print(f"   -> WARNING: on a cache hit Ollama reports only {int(ph)} prompt tokens (miss: {int(pm)}). The "
                      "context_too_small guard compares that count with the prompt size, so a cached follow-up could "
                      "be refused falsely. Tell me and I will make the guard cache-aware.")

    print("\n5. PREFILL SPEED (uncached, system prompt only vs whole prompt)")
    rate: dict[str, list[dict[str, Any]]] = {"system only": [], "sys+24 hist": []}
    for i in range(args.reps):
        await call(base, payload(0, system=f"[{i}x] " + sysmsg, predict=1), T)
        rate["system only"].append(await call(base, payload(0, system=f"[{i}a] " + sysmsg, predict=1), T))
        rate["sys+24 hist"].append(await call(base, payload(24, system=f"[{i}b] " + sysmsg, predict=1), T))
    table("   uncached", rate)
    for k, rows in rate.items():
        tok, pe = statistics.median(r["ptok"] for r in rows), statistics.median(r["pe"] for r in rows)
        if pe:
            print(f"   {k}: about {tok / (pe / 1000):.0f} prompt tokens per second of prompt evaluation")

    print("\nHow to read this (the script does not decide for you):")
    print(" - prompt-eval ms close to first-token ms in the prefill table => time is spent READING the prompt.")
    print(" - cache hit much faster than miss => prefix caching works; first-token cost of the fixed rules is paid once per")
    print("   conversation (and again whenever the start of the prompt changes), not on every message.")
    print(" - prefill tokens/s of a few hundred or less on a 9B model => CPU is involved (see section 1).")
    print(" - history conditions with overlapping medians => history length is not what moves first-token time.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
