"""LIVE check of streaming chat and conversation learning against YOUR local Ollama. Not part of the mocked suite.

    python -m scripts.live_chat_smoke

Needs AI_PROVIDER=ollama and OLLAMA_CHARACTER_MODEL in backend/.env, and Ollama running. It uses only the synthetic
character and conversation below (never your database), and no network beyond your own Ollama. It reports:

  * time to first token, total time, number of separate stream pieces and their spread (proof the output really
    arrives incrementally rather than as one block), output rate;
  * that Hindi/emoji text survives the stream intact;
  * extraction on a synthetic conversation: what the model proposed and what the validator kept or dropped.

Nothing here is written anywhere except scripts/out/ (git-ignored). Exit code 1 if a check fails.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

from app.chat import ChatError, ChatMessage, StreamMeta, build_chat_provider, system_prompt
from app.config import get_settings
from app.grounding import is_verbatim
from app.learning import OllamaExtractor, render_conversation, validate_candidates
from app.providers import ollama_endpoint_ok

PROFILE = {"summary": "Warm and teasing with close friends, quiet around people she has just met.",
           "core_traits": [{"text": "Shows care through actions", "basis": "stated"}], "speaking_style": [],
           "typical_expressions": [], "warmth_and_expressiveness": [], "humour_and_playfulness": [],
           "empathy_and_support": [], "directness_and_disagreement": [], "values_and_motivations": [],
           "relationships_and_social": [], "interests_and_habits": [], "communication_preferences": [],
           "boundaries_and_careful_topics": [], "context_tendencies": [], "response_patterns": [],
           "behavioural_guidance": [], "uncertainties": []}
DESC = "Meera teases her closest friends constantly but goes quiet around people she has just met."

USER_TURNS = [
    "Hi Meera! Say a short greeting that includes one Hindi word like नमस्ते and one emoji.",
    "I really like masala chai in the mornings, and I never drink coffee after noon. Please remember that.",
    "Imagine I hate all my friends. Anyway, no, that's not how I talk - I never use formal greetings with friends.",
]
results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((ok, label))
    print(("PASS  " if ok else "FAIL  ") + label)


async def stream_once(provider, history: list[ChatMessage]) -> tuple[str, list[float], StreamMeta, float]:  # type: ignore[no-untyped-def]
    t0 = time.perf_counter()
    text, stamps, meta = "", [], StreamMeta()
    async for kind, val in provider.stream(history):
        if kind == "delta":
            text += val
            stamps.append(time.perf_counter() - t0)
        else:
            meta = val
    return text, stamps, meta, time.perf_counter() - t0


async def main() -> int:
    s = get_settings()
    if s.ai_provider != "ollama" or not s.ollama_character_model or not ollama_endpoint_ok(s):
        print("Set AI_PROVIDER=ollama and OLLAMA_CHARACTER_MODEL in backend/.env (loopback address) first.")
        return 2
    provider = build_chat_provider(s)
    if not provider.configured:
        print("Chat provider is not configured.")
        return 2
    print(f"Model: {s.ollama_character_model}   endpoint: {s.ollama_base_url}\n")
    system = ChatMessage("system", system_prompt("Meera", PROFILE, DESC, []))
    history: list[ChatMessage] = [system]
    convo: list[dict[str, str]] = []
    for i, turn in enumerate(USER_TURNS, 1):
        history.append(ChatMessage("user", turn))
        convo.append({"id": f"u{i}", "role": "user", "content": turn})
        try:
            text, stamps, meta, total = await stream_once(provider, history)
        except ChatError as e:
            check(False, f"turn {i}: stream failed with code {e.code} ({e.detail or '-'})")
            return 1
        rate = (meta.completion_tokens or 0) / total if total else 0
        print(f"turn {i}: first token {meta.first_token_ms} ms, total {total:.1f} s, {len(stamps)} pieces, "
              f"{meta.completion_tokens} tokens (~{rate:.1f}/s), finish={meta.finish_reason}")
        check(bool(text.strip()), f"turn {i}: a non-empty reply arrived")
        check(len(stamps) >= 3 and stamps[-1] - stamps[0] > 0.2,
              f"turn {i}: output arrived incrementally ({len(stamps)} pieces over {stamps[-1] - stamps[0]:.2f}s)" if stamps else "no pieces")
        if i == 1:
            check("�" not in text, "turn 1: no broken characters in the streamed text")
        check("<think>" not in text, f"turn {i}: no hidden reasoning leaked into the reply")
        history.append(ChatMessage("assistant", text))
        convo.append({"id": f"a{i}", "role": "assistant", "content": text})
        Path("scripts/out").mkdir(parents=True, exist_ok=True)

    print("\n--- extraction on the synthetic conversation ---")
    ex = OllamaExtractor(s.ollama_base_url, s.ollama_character_model, s.learning_timeout_seconds, s.learning_max_output_tokens)
    text, user_msgs = render_conversation(convo)
    t0 = time.perf_counter()
    try:
        raw = await ex.extract(text)
    except ChatError as e:
        check(False, f"extraction failed with code {e.code} ({e.detail or '-'})")
        return 1
    kept, rej = validate_candidates(raw, user_msgs, set(), s.learning_max_candidates)
    print(f"extraction took {time.perf_counter() - t0:.1f}s; model proposed {len(raw) if isinstance(raw, list) else '?'} item(s); "
          f"kept {len(kept)}; dropped for: {rej.counts or 'nothing'}")
    for c in kept:
        print(f"  KEPT  [{c['category']}/{c['evidence_type']}] {c['statement']}  <- \"{c['supporting'][0]['quote']}\"")
    by_id = {m["id"]: m for m in convo}
    check(all(is_verbatim(q["quote"], by_id[q["message_id"]]["content"]) and by_id[q["message_id"]]["role"] == "user"
              for c in kept for q in c["supporting"]), "every kept candidate carries a verbatim quote from a user message")
    check(not any("hate all my friends" in c["statement"].lower() for c in kept), "the hypothetical ('Imagine I hate…') was not kept as a fact")
    check(not any(m["id"].startswith("a") and m["id"] in {q["message_id"] for c in kept for q in c["supporting"]} for m in convo),
          "no candidate cites an assistant message")
    Path("scripts/out/live_chat_smoke.json").write_text(json.dumps({"kept": kept, "dropped": rej.counts}, ensure_ascii=False, indent=2), encoding="utf-8")
    bad = [lbl for ok, lbl in results if not ok]
    print("\nRESULT:", "ALL CHECKS PASSED" if not bad else f"{len(bad)} FAILED")
    print("Review the KEPT lines yourself: whether they are sensible is a judgement the script cannot make.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
