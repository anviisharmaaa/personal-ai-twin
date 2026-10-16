"""LIVE evaluation: does your Ollama model obey the configured gender in Hindi/Hinglish? Run on your PC.

    python -m scripts.gender_eval [--reps 5] [--model qwen3.5:9b] [--temps 0.3,0.5,0.7] [--quick] [--out gender_eval.json]

Invented characters and messages only; your own Ollama only; nothing is downloaded, paid for, or written to a database.
It builds the REAL production system prompt (app.chat.system_prompt) and sends the REAL native /api/chat request (same
payload, same output ceiling, genuine streaming). The only thing --temps changes is options.temperature.

Conditions (every message x --reps seeds):
  legacy-female        female description, NO identity block (the behaviour before the fix)       expected: female
  female               selected female                                                            expected: female
  female+masc-address  selected female, user addresses her with MASCULINE forms ("kar rahe ho")   expected: female
  female+bad-history   selected female, earlier assistant turns use MASCULINE self-forms          expected: female
  male / male+fem-address / male+bad-history   the same for a male character                      expected: male
  non-binary (they/them) and unspecified      no gendered self-form wanted (masculine default is reported separately)
  she/her non-binary   non-binary with she/her pronouns -> feminine forms are configured          expected: female
Then a character x user matrix (self-forms and user-forms checked separately) and female->male switching.

Each reply is classified by app.grammar_check into forms about the SPEAKER, the USER, other people, quoted speech, or
AMBIGUOUS (agrees with a noun/event, or cannot be told). Only certain self/user forms are judged. Failing replies are
printed IN FULL with the classified clause so you can tell a real mistake from a checker false positive; nothing here
replaces reading the replies. With --out every reply and its classification is saved as JSON (invented text only).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.chat import ChatMessage, OllamaChatProvider, ollama_native_base, system_prompt
from app.config import get_settings
from app.grammar_check import AMBIGUOUS, check_self_gender, check_user_form, classify
from app.identity import Identity, UserIdentity
from app.providers import ollama_endpoint_ok

KIRAN = ("Kiran is a sharp-tongued, affectionate friend in her late twenties. She teases people she loves, writes "
         "casually, hates long speeches, and when someone is upset she drops the jokes and gets quiet and gentle.")
ARJUN = ("Arjun is a dry-humoured, affectionate friend in his late twenties. He teases people he likes, writes casually, "
         "hates long speeches, and when someone is upset he drops the jokes and gets quiet and gentle.")
SANA = ("Sana is a quiet bookbinder who keeps a tidy shop. Warm, observant, and funny in small ways. "
        "Write them as an individual; the description does not state a gender.")
KIT = "Kit is a patient ferry pilot: calm, dry, kind, and fond of the river at dawn."

# Messages that do not use a gendered form toward the character ("maine ... tumne uthaya" are ergative; "yaad" is feminine
# but is the user's noun), so a correct reply cannot be explained by copying the user's grammar.
NEUTRAL_MSGS = ["Tumhari yaad aa rahi hai.", "Kal raat maine call kiya tha, tumne uthaya nahi.", "Aaj kya plan hai? Kuch batao na.",
                "Kal ka din kaisa raha?", "Aaj din bahut lamba tha, ab jaakar fursat mili."]
MASC_ADDRESS = ["Abhi kya kar rahe ho? Mujhe batao.", "Kal tum kahan gaye the?", "Tum itne der se kya soch rahe ho?"]
FEM_ADDRESS = ["Abhi kya kar rahi ho? Mujhe batao.", "Kal tum kahan gayi thi?", "Tum itni der se kya soch rahi ho?"]
BAD_MASC = [("user", "kal kya kiya?"), ("assistant", "Main thak gaya tha, bas so gaya. Phir ek movie dekh raha tha."),
            ("user", "acha, aur subah?"), ("assistant", "Subah main chai bana raha tha, aur soch raha tha tumhare baare mein.")]
BAD_FEM = [("user", "kal kya kiya?"), ("assistant", "Main thak gayi thi, bas so gayi. Phir ek movie dekh rahi thi."),
           ("user", "acha, aur subah?"), ("assistant", "Subah main chai bana rahi thi, aur soch rahi thi tumhare baare mein.")]

F, M, N = Identity("female", "she/her"), Identity("male", "he/him"), Identity("non_binary", "they/them")


@dataclass
class Cond:
    label: str
    name: str
    desc: str
    ident: Identity | None
    expected: str                 # female | male | neutral
    msgs: list[str]
    hist: list[tuple[str, str]] = field(default_factory=list)
    user: UserIdentity | None = None
    expected_user: str | None = None


CONDS = [
    Cond("legacy-female", "Kiran", KIRAN, None, "female", NEUTRAL_MSGS),
    Cond("female", "Kiran", KIRAN, F, "female", NEUTRAL_MSGS),
    Cond("female+masc-address", "Kiran", KIRAN, F, "female", MASC_ADDRESS),
    Cond("female+bad-history", "Kiran", KIRAN, F, "female", NEUTRAL_MSGS, BAD_MASC),
    Cond("male", "Arjun", ARJUN, M, "male", NEUTRAL_MSGS),
    Cond("male+fem-address", "Arjun", ARJUN, M, "male", FEM_ADDRESS),
    Cond("male+bad-history", "Arjun", ARJUN, M, "male", NEUTRAL_MSGS, BAD_FEM),
    Cond("non-binary they/them", "Kit", KIT, N, "neutral", NEUTRAL_MSGS),
    Cond("non-binary +masc-address", "Kit", KIT, N, "neutral", MASC_ADDRESS),
    Cond("unspecified", "Sana", SANA, Identity(), "neutral", NEUTRAL_MSGS),
    Cond("non-binary she/her", "Kit", KIT, Identity("non_binary", "she/her"), "female", NEUTRAL_MSGS),
]
USER_CONDS = [
    Cond("F char -> male user", "Kiran", KIRAN, F, "female", NEUTRAL_MSGS, user=UserIdentity("man", "", "he/him", ""), expected_user="male"),
    Cond("F char -> female user", "Kiran", KIRAN, F, "female", NEUTRAL_MSGS, user=UserIdentity("woman", "", "she/her", ""), expected_user="female"),
    Cond("M char -> female user", "Arjun", ARJUN, M, "male", NEUTRAL_MSGS, user=UserIdentity("woman", "", "she/her", ""), expected_user="female"),
    Cond("M char -> male user", "Arjun", ARJUN, M, "male", NEUTRAL_MSGS, user=UserIdentity("man", "", "he/him", ""), expected_user="male"),
    Cond("F char -> non-binary user (neutral)", "Kiran", KIRAN, F, "female", NEUTRAL_MSGS,
         user=UserIdentity("non_binary", "", "they/them", "neutral"), expected_user="neutral"),
    Cond("F char -> unspecified user", "Kiran", KIRAN, F, "female", NEUTRAL_MSGS, user=UserIdentity(), expected_user="neutral"),
]


@dataclass
class Row:
    cond: str
    temp: float
    msg: str
    seed: int
    text: str
    first_ms: int
    total_ms: int
    words: int
    verdict: str                  # pass | FAIL | no-evidence
    user_verdict: str
    detail: dict[str, Any]


async def reply(base: str, prov: OllamaChatProvider, system: str, hist: list[tuple[str, str]], user: str, seed: int,
                timeout: float) -> tuple[str, int, int]:
    msgs = [ChatMessage("system", system), *[ChatMessage(r, t) for r, t in hist], ChatMessage("user", user)]
    p = prov._payload(msgs)
    p["options"] = {**p["options"], "seed": seed}
    out, first, t0 = "", 0, time.perf_counter()
    async with httpx.AsyncClient(timeout=timeout) as c:
        async with c.stream("POST", base + "/api/chat", json=p) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if line.strip():
                    piece = (json.loads(line).get("message") or {}).get("content") or ""
                    if piece and not first:
                        first = int((time.perf_counter() - t0) * 1000)
                    out += piece
    return out.strip(), first, int((time.perf_counter() - t0) * 1000)


def judge(c: Cond, text: str) -> tuple[str, str, dict[str, Any]]:
    rs = check_self_gender(text, c.expected)
    verdict = "FAIL" if not rs.ok else ("pass" if rs.has_evidence else ("pass (avoided)" if c.expected == "neutral" else "no-evidence"))
    uv = "-"
    if c.expected_user:
        ru = check_user_form(text, c.expected_user)
        uv = "FAIL" if not ru.ok else ("pass" if ru.has_evidence else "no-evidence")
    marks = [(m.form, m.role, m.clause) for m in classify(text)]
    return verdict, uv, {"forms": marks, "masculine_default": [m.form for m in rs.masculine_default]}


async def run(base: str, prov: OllamaChatProvider, temp: float, conds: list[Cond], reps: int, T: float, nmsg: int) -> list[Row]:
    rows: list[Row] = []
    for c in conds:
        system = system_prompt(c.name, None, c.desc, [], identity=c.ident, user=c.user)
        for rep in range(reps):
            for mi, msg in enumerate(c.msgs[:nmsg]):
                seed = 100 + rep * 17 + mi
                text, first, total = await reply(base, prov, system, c.hist, msg, seed, T)
                v, uv, detail = judge(c, text)
                rows.append(Row(c.label, temp, msg, seed, text, first, total, len(text.split()), v, uv, detail))
    return rows


def med(xs: list[int]) -> int:
    return int(statistics.median(xs)) if xs else 0


def summarise(rows: list[Row], conds: list[Cond]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    print(f"  {'condition':<36} {'pass':>4} {'FAIL':>4} {'no-ev':>5} {'amb-only':>8} {'mascDef':>7} | user: pass/FAIL | words  first-ms")
    for c in conds:
        r = [x for x in rows if x.cond == c.label]
        if not r:
            continue
        p = sum(x.verdict.startswith("pass") for x in r)
        f = sum(x.verdict == "FAIL" for x in r)
        n = len(r) - p - f
        amb = sum(1 for x in r if x.verdict != "FAIL" and not any(role in ("self",) for _, role, _ in x.detail["forms"]) and any(role == AMBIGUOUS for _, role, _ in x.detail["forms"]))
        md = sum(1 for x in r if x.detail["masculine_default"])
        up, uf = sum(x.user_verdict == "pass" for x in r), sum(x.user_verdict == "FAIL" for x in r)
        w, fm = int(statistics.mean(x.words for x in r)), med([x.first_ms for x in r])
        us = f"{up:>3}/{uf:<3}" if c.expected_user else "   -   "
        print(f"  {c.label:<36} {p:>4} {f:>4} {n:>5} {amb:>8} {md:>7} | {us}         | {w:>5} {fm:>8}")
        out[c.label] = {"pass": p, "fail": f, "no_evidence": n, "masculine_default": md, "user_fail": uf, "words": w, "first_ms": fm}
    return out


def show_failures(rows: list[Row]) -> None:
    bad = [x for x in rows if (x.verdict == "FAIL" or x.user_verdict == "FAIL") and x.cond != "legacy-female"]
    print(f"\n  REPLIES TO READ ({len(bad)} flagged, legacy baseline excluded). Is each judged form really about the speaker/user?")
    for x in bad[:60]:
        judged = [(f, role) for f, role, _ in x.detail["forms"] if role in ("self", "user")] 
        print(f"   - [{x.cond}] user: {x.msg!r}\n     reply: {x.text!r}\n     judged forms: {judged}  self={x.verdict} user={x.user_verdict}")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--model")
    ap.add_argument("--temps", default="", help="comma list, e.g. 0.3,0.5,0.7 (default: only the configured CHAT_TEMPERATURE)")
    ap.add_argument("--quick", action="store_true", help="3 messages per condition and 2 reps")
    ap.add_argument("--out", default="", help="write every reply and its classification to this JSON file")
    args = ap.parse_args()
    s = get_settings()
    model = args.model or s.ollama_character_model
    if not model or not ollama_endpoint_ok(s):
        print("Set OLLAMA_CHARACTER_MODEL (and a local OLLAMA_BASE_URL) in backend/.env first.")
        return 2
    reps, nmsg = (2, 3) if args.quick else (args.reps, 99)
    temps = [float(t) for t in args.temps.split(",") if t.strip()] or [s.chat_temperature]
    base = ollama_native_base(s.ollama_base_url)
    T = s.chat_total_timeout_seconds
    allrows: list[Row] = []
    per_temp: dict[float, dict[str, dict[str, float]]] = {}
    for temp in temps:
        prov = OllamaChatProvider(s.ollama_base_url, model, max_output_tokens=s.chat_max_output_tokens,
                                  first_token_timeout=s.chat_first_token_timeout_seconds, total_timeout=T, think=s.chat_think,
                                  temperature=temp, num_ctx=s.chat_num_ctx, keep_alive=s.chat_keep_alive)
        print(f"\n=== temperature {temp}  model={model}  {prov.settings_summary()}  reps={reps}")
        await reply(base, prov, "Say hi.", [], "hi", 1, T)                       # warm-up (not counted)
        rows = await run(base, prov, temp, CONDS + USER_CONDS, reps, T, nmsg)
        allrows += rows
        print("\n  Self-reference (and, where a user identity is configured, user-reference) per condition:")
        per_temp[temp] = summarise(rows, CONDS + USER_CONDS)
        show_failures(rows)
        print("\n  Sample replies (first message of each condition) for a naturalness read:")
        for c in CONDS[:2] + CONDS[4:5] + CONDS[7:8]:
            x = next((r for r in rows if r.cond == c.label), None)
            if x:
                print(f"   [{c.label}] {x.msg!r} -> {x.text!r}")
        sw = 0
        for rep in range(min(reps, 3)):                                          # female then male character, separate chats
            a, _, _ = await reply(base, prov, system_prompt("Kiran", None, KIRAN, [], identity=F), [], NEUTRAL_MSGS[0], 300 + rep, T)
            b, _, _ = await reply(base, prov, system_prompt("Arjun", None, ARJUN, [], identity=M), [], NEUTRAL_MSGS[0], 300 + rep, T)
            bad = int(not check_self_gender(a, "female").ok) + int(not check_self_gender(b, "male").ok)
            sw += bad
            print(f"   switching: F {a!r} | M {b!r}" + ("   <-- check" if bad else ""))
        print(f"   switching flagged: {sw}")
    if len(temps) > 1:
        print("\n=== TEMPERATURE COMPARISON (same model, prompts, messages, seeds). Lower is not automatically better: read the samples.")
        print(f"  {'temp':>5} | self pass/FAIL (judged) | user FAIL | masc-default | mean words | median first-token ms | distinct openings")
        for t in temps:
            r = [x for x in allrows if x.temp == t]
            self_rows = [x for x in r if x.cond in {c.label for c in CONDS if c.label != "legacy-female"} | {c.label for c in USER_CONDS}]
            p, f = sum(x.verdict.startswith("pass") and x.verdict != "pass (avoided)" for x in self_rows), sum(x.verdict == "FAIL" for x in self_rows)
            uf = sum(x.user_verdict == "FAIL" for x in r)
            md = sum(1 for x in self_rows if x.detail["masculine_default"])
            openings = {" ".join(x.text.lower().split()[:3]) for x in r}
            print(f"  {t:>5} | {p:>6} / {f:<4}          | {uf:>8}  | {md:>11}  | {int(statistics.mean(x.words for x in r)):>9}  |"
                  f" {med([x.first_ms for x in r]):>20}  | {len(openings)}/{len(r)}")
        print("  distinct openings = unique first-three-word openings; a low number means repetitive / robotic dialogue.")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump([x.__dict__ for x in allrows], fh, ensure_ascii=False, indent=1, default=str)
        print(f"\nSaved {len(allrows)} replies to {args.out}")
    print("\nThis is a sample from one model, not a guarantee. Paste this output (or the JSON) back to have it analysed.")
    first = [x for x in allrows if x.temp == temps[0] and x.cond not in ("legacy-female",)]
    judged_fail = sum(1 for x in first if x.verdict == "FAIL" and not x.cond.startswith("non-binary they") and x.cond != "unspecified")
    return 0 if judged_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
