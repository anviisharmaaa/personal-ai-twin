"""LIVE end-to-end check of multiple characters + real streamed chat, against YOUR running stack. Run it on your PC.

    # 1. backend running (uvicorn app.main:app) against your DEVELOPMENT Supabase, Ollama running with your model
    # 2. one throw-away dev account (email confirmed), credentials in the environment, never printed:
    $env:MADHUORA_TEST_A_EMAIL = "..."; $env:MADHUORA_TEST_A_PASSWORD = "..."
    python -m scripts.live_multi_character_check [--backend http://localhost:8000]

It talks to the REAL backend, the REAL database (so it proves the multiple-characters migration is applied) and your
REAL local Ollama model. It uses only invented characters and invented messages - nothing from your own life - and
needs the AI-processing consent for the current provider (grant it once in Settings with this account).

What it does and reports PASS/FAIL for:
  1. creates two invented characters (a gruff sailor, an exuberant street-food vendor) via POST /characters;
  2. both appear in GET /characters, with the account's self-twin untouched;
  3. starts a conversation with EACH and streams a real reply over SSE (counts the separate delta events, time to
     first word, total time) - proving tokens arrive incrementally from Ollama;
  4. checks each reply was saved as `complete`, and reloads each conversation from the database;
  5. starts a SECOND conversation with the first character; it starts empty and the first is unchanged;
  6. sends a follow-up and re-reads history: only that conversation's messages, in order;
  7. prints both replies so YOU can judge whether each sounds like its own character (a script cannot judge style);
  8. leaves the invented characters in the account (so you can open them in the browser). Delete them in Supabase
     if you do not want them: they are named "TEST Arjun (live check)" and "TEST Isha (live check)".

Exit code 1 if any check fails; 2 if it could not start (missing env, backend down, migration not applied).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid

import httpx

from app.config import get_settings

results: list[tuple[bool, str]] = []
ARJUN = ("Arjun is a gruff retired sailor in his sixties. He speaks in short, blunt sentences, distrusts fancy words, "
         "hums sea shanties when he is content, and calls everyone 'lad' or 'lass'. He is kind underneath but hates "
         "showing it.")
ISHA = ("Isha is an exuberant street-food vendor in her thirties. She laughs loudly, teases her customers, calls "
        "everyone 'boss', talks fast, and gets excited about spices. She is generous and never lets anyone leave hungry.")


def check(ok: bool, label: str, detail: str = "") -> None:
    results.append((ok, label))
    print(("PASS  " if ok else "FAIL  ") + label + (f"  [{detail}]" if detail else ""))


def sign_in(base: str, key: str, email: str, password: str) -> str:
    r = httpx.post(f"{base}/auth/v1/token", params={"grant_type": "password"}, headers={"apikey": key},
                   json={"email": email, "password": password}, timeout=20)
    if r.status_code != 200:
        raise SystemExit(f"Sign-in failed (HTTP {r.status_code}). Confirm the test account's email and password.")
    return str(r.json()["access_token"])


def stream(api: str, h: dict[str, str], cid: str, text: str) -> tuple[str, list[float], str | None, float]:
    """Returns (reply, delta arrival times, error code or None, seconds). Reads the SSE stream incrementally."""
    t0 = time.perf_counter()
    reply, stamps, event, err = "", [], "", None
    with httpx.stream("POST", f"{api}/conversations/{cid}/messages/stream", headers=h, timeout=httpx.Timeout(600, connect=10),
                      json={"content": text, "client_message_id": uuid.uuid4().hex}) as r:
        if r.status_code != 200:
            return "", [], f"http_{r.status_code}:{r.read().decode()[:200]}", time.perf_counter() - t0
        for line in r.iter_lines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data = json.loads(line[5:].strip())
                if event == "delta":
                    reply += data.get("text", "")
                    stamps.append(time.perf_counter() - t0)
                elif event == "error":
                    err = str(data.get("code"))
    return reply, stamps, err, time.perf_counter() - t0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="http://localhost:8000")
    args = ap.parse_args()
    s = get_settings()
    if not os.environ.get("MADHUORA_TEST_A_EMAIL") or not os.environ.get("MADHUORA_TEST_A_PASSWORD"):
        print("Set MADHUORA_TEST_A_EMAIL and MADHUORA_TEST_A_PASSWORD first (a throw-away development account).")
        return 2
    base, key = s.supabase_url.rstrip("/"), s.supabase_publishable_key
    token = sign_in(base, key, os.environ["MADHUORA_TEST_A_EMAIL"], os.environ["MADHUORA_TEST_A_PASSWORD"])
    api = args.backend.rstrip("/") + "/api/v1"
    h = {"Authorization": f"Bearer {token}"}
    try:
        st = httpx.get(f"{api}/chat/status", headers=h, timeout=20).json()
    except httpx.HTTPError as exc:
        print(f"Backend not reachable at {args.backend}: {type(exc).__name__}. Start it first.")
        return 2
    print(f"chat status: available={st.get('available')} reason={st.get('reason')} provider={st.get('provider')}")
    if st.get("reason") in ("consent_required", "no_twin"):
        print("Grant AI consent / create your twin in the app with this account first, then re-run.")
        return 2
    if st.get("provider") != "ollama":
        print("AI_PROVIDER is not ollama on this backend: this check is about the real local model.")
        return 2

    made = []
    for name, desc in (("TEST Arjun (live check)", ARJUN), ("TEST Isha (live check)", ISHA)):
        r = httpx.post(f"{api}/characters", headers=h, json={"name": name, "description": desc}, timeout=30)
        if r.status_code == 503 and "migration_required" in r.text:
            print("The database has NOT been migrated for multiple characters: apply "
                  "supabase/migrations/20261015200000_multiple_characters.sql, then re-run.")
            return 2
        check(r.status_code == 201, f"created {name}", f"HTTP {r.status_code}")
        if r.status_code != 201:
            return 1
        made.append(r.json()["twin"]["id"])
    arjun, isha = made
    chars = httpx.get(f"{api}/characters", headers=h, timeout=30).json()["characters"]
    ids = {c["id"]: c for c in chars}
    check(arjun in ids and isha in ids, "both characters are listed")
    check(sum(1 for c in chars if c.get("is_self")) == 1, "exactly one self-twin is still present")

    convs, replies = {}, {}
    for label, cid_char in (("Arjun", arjun), ("Isha", isha)):
        r = httpx.post(f"{api}/conversations", headers=h, json={"character_id": cid_char}, timeout=30)
        check(r.status_code == 201 and r.json()["character_id"] == cid_char, f"conversation started with {label}")
        convs[label] = r.json()["id"]
        reply, stamps, err, secs = stream(api, h, convs[label], "Hello! Who are you, and what is your favourite thing about your day?")
        spread = (stamps[-1] - stamps[0]) if len(stamps) > 1 else 0.0
        check(err is None and bool(reply.strip()), f"{label}: a real reply streamed from Ollama", err or "")
        check(len(stamps) >= 3 and spread > 0.2, f"{label}: tokens arrived incrementally",
              f"{len(stamps)} pieces, first at {stamps[0]:.1f}s, spread {spread:.1f}s, total {secs:.1f}s" if stamps else "no pieces")
        replies[label] = reply
        msgs = httpx.get(f"{api}/conversations/{convs[label]}/messages", headers=h, timeout=30).json()["messages"]
        check([m["role"] for m in msgs] == ["user", "assistant"] and msgs[-1]["status"] == "complete",
              f"{label}: saved as user + complete assistant message after reload")

    r = httpx.post(f"{api}/conversations", headers=h, json={"character_id": arjun}, timeout=30)
    second = r.json()["id"]
    check(second != convs["Arjun"], "a second, separate conversation with the same character was created")
    check(httpx.get(f"{api}/conversations/{second}/messages", headers=h, timeout=30).json()["messages"] == [],
          "the new conversation starts empty")
    reply, _, err, _ = stream(api, h, second, "Tell me one short thing about the sea.")
    check(err is None and bool(reply.strip()), "Arjun: follow-up in the second conversation streamed")
    first = httpx.get(f"{api}/conversations/{convs['Arjun']}/messages", headers=h, timeout=30).json()["messages"]
    check(len(first) == 2, "the first Arjun conversation is unchanged by the second")
    listed = httpx.get(f"{api}/conversations", params={"character_id": isha}, headers=h, timeout=30).json()["conversations"]
    check([c["id"] for c in listed] == [convs["Isha"]], "Isha's conversation list contains only Isha's conversation")

    print("\n--- read these two replies and judge: does each sound like ITS character? (a script cannot) ---")
    print(f"Arjun (gruff sailor):\n  {replies['Arjun'].strip()[:600]}\n")
    print(f"Isha (exuberant vendor):\n  {replies['Isha'].strip()[:600]}\n")
    bad = [label for ok, label in results if not ok]
    print(f"{len(results) - len(bad)}/{len(results)} checks passed" + (": ALL PASSED" if not bad else f"; FAILED: {bad}"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
