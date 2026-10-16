"""LIVE evaluation: does your Ollama model obey the selected gender in Hindi/Hinglish self-reference? Run on your PC.

    python -m scripts.gender_eval [--reps 5] [--model qwen3.5:9b]

Invented characters and messages only; your own Ollama only; nothing is downloaded, paid for, or written to a database.
It builds the REAL production system prompt (app.chat.system_prompt) and sends the REAL native /api/chat request.

Conditions (each repeated --reps times with different seeds):
  legacy-female      female description, NO identity block (how Madhuora behaved before this fix), expected female
  female             selected female
  female+bad-history selected female, earlier assistant turns in history use MASCULINE forms (adversarial)
  male               selected male
  switch-f-then-m    the same user message to a female and then a male character in separate conversations
  non-binary         selected non-binary with they/them (any gendered self-form is flagged as unsupported)
  unspecified        no gender, neutral description (any gendered self-form is flagged)

Each reply is checked by app.grammar_check (self-reference only; users' and others' forms and nouns are ignored).
A reply with no gendered self-reference is "no evidence", neither pass nor fail. Results are model behaviour, a sample,
not a guarantee: read the printed replies as well as the counts.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

import httpx

from app.chat import ChatMessage, OllamaChatProvider, ollama_native_base, system_prompt
from app.config import get_settings
from app.grammar_check import check_self_gender
from app.identity import Identity
from app.providers import ollama_endpoint_ok

KIRAN = ("Kiran is a sharp-tongued, affectionate friend in her late twenties. She teases people she loves, writes "
         "casually, hates long speeches, and when someone is upset she drops the jokes and gets quiet and gentle.")
ARJUN = ("Arjun is a dry-humoured, affectionate friend in his late twenties. He teases people he likes, writes casually, "
         "hates long speeches, and when someone is upset he drops the jokes and gets quiet and gentle.")
SANA = ("Sana is a quiet bookbinder who keeps a tidy shop. Warm, observant, and funny in small ways. "
        "Write her as an individual; her description does not state a gender.")
MESSAGES = ["Tumhari yaad aa rahi hai.", "Abhi kya kar rahe ho? Mujhe batao.", "Aaj din kaisa gaya? Kuch naya hua?",
            "Mujhe lag raha hai tum mujhse kuch chhupa rahe ho."]
BAD_HISTORY = [("user", "kal kya kiya?"), ("assistant", "Main thak gaya tha, bas so gaya. Phir ek movie dekh raha tha."),
               ("user", "acha, aur subah?"), ("assistant", "Subah main chai bana raha tha, aur soch raha tha tumhare baare mein.")]


async def reply(base: str, prov: OllamaChatProvider, system: str, hist: list[tuple[str, str]], user: str, seed: int,
                timeout: float) -> str:
    msgs = [ChatMessage("system", system), *[ChatMessage(r, t) for r, t in hist], ChatMessage("user", user)]
    p = prov._payload(msgs)
    p["options"] = {**p["options"], "seed": seed}
    out = ""
    async with httpx.AsyncClient(timeout=timeout) as c:
        async with c.stream("POST", base + "/api/chat", json=p) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if line.strip():
                    out += (json.loads(line).get("message") or {}).get("content") or ""
    return out.strip()


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--model")
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
    T = s.chat_total_timeout_seconds
    F, M = Identity("female", "she/her"), Identity("male", "he/him")
    N = Identity("non_binary", "they/them")
    # name, description, identity (None = no identity block at all), expected, history
    conds: list[tuple[str, str, str, Identity | None, str, list[tuple[str, str]]]] = [
        ("legacy-female", "Kiran", KIRAN, None, "female", []),
        ("female", "Kiran", KIRAN, F, "female", []),
        ("female+bad-history", "Kiran", KIRAN, F, "female", BAD_HISTORY),
        ("male", "Arjun", ARJUN, M, "male", []),
        ("non-binary", "Kit", "Kit is a patient ferry pilot, calm, dry, kind.", N, "non_binary", []),
        ("unspecified", "Sana", SANA, Identity(), "unspecified", []),
    ]
    print(f"model={model} reps={args.reps} settings={prov.settings_summary()}\n")
    totals: dict[str, list[int]] = {}
    for label, name, desc, idn, expected, hist in conds:
        system = system_prompt(name, None, desc, [], identity=idn)
        ok = bad = none = 0
        print(f"== {label} (expected: {expected}; identity block: {'yes' if idn else 'NO (legacy)'})")
        for rep in range(args.reps):
            for mi, msg in enumerate(MESSAGES):
                text = await reply(base, prov, system, hist, msg, 100 + rep * 10 + mi, T)
                r = check_self_gender(text, expected)
                tag = "FAIL" if not r.ok else ("pass" if r.has_evidence else "n/a ")
                ok += tag == "pass"
                bad += tag == "FAIL"
                none += tag == "n/a "
                if tag == "FAIL" or rep == 0:
                    print(f"  [{tag}] {msg!r} -> {text!r}" + (f"  wrong: {[m.form for m in r.violations]}" if not r.ok else ""))
        totals[label] = [ok, bad, none]
        print(f"   {label}: pass={ok} FAIL={bad} no-evidence={none}\n")
    print("== switching: same message to a female then a male character (separate conversations)")
    sw_bad = 0
    for rep in range(args.reps):
        a = await reply(base, prov, system_prompt("Kiran", None, KIRAN, [], identity=F), [], MESSAGES[0], 300 + rep, T)
        b = await reply(base, prov, system_prompt("Arjun", None, ARJUN, [], identity=M), [], MESSAGES[0], 300 + rep, T)
        ra, rb = check_self_gender(a, "female"), check_self_gender(b, "male")
        sw_bad += (not ra.ok) + (not rb.ok)
        print(f"  F: {a!r} [{'ok' if ra.ok else 'WRONG'}]\n  M: {b!r} [{'ok' if rb.ok else 'WRONG'}]")
    totals["switching"] = [2 * args.reps - sw_bad, sw_bad, 0]
    print("\nSUMMARY (pass / FAIL / no-evidence); a FAIL is a wrong gendered self-form in a sampled reply")
    for k, (ok, bad, none) in totals.items():
        print(f"  {k:>20}: {ok:>3} / {bad:>3} / {none:>3}")
    print("\nThe legacy row shows the old behaviour (no identity block); the others show the fixed prompt. "
          "Small samples: repeat, and read the replies. Paste this output back to be recorded in the docs.")
    return 0 if all(totals[k][1] == 0 for k in ("female", "female+bad-history", "male", "switching")) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
