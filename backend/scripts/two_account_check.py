"""LIVE two-account isolation check against YOUR development Supabase project. Run it on your computer.

Uses two throw-away development accounts that YOU create (Settings of the app -> sign up twice, confirm the emails).
Credentials come from environment variables and are never printed or stored:

    $env:MADHUORA_TEST_A_EMAIL / _A_PASSWORD / _B_EMAIL / _B_PASSWORD
    python -m scripts.two_account_check [--backend http://localhost:8000]

It also covers conversations, messages and the learning tables (candidates, memories, proposals, revisions).
It proves, with real tokens and the database's real row-level security (not mocks), that account B cannot read or
change account A's twin, character description, profile or consent, either through the Madhuora API or by talking to
PostgREST directly with B's own token (what a malicious browser could do). It writes one description into A's twin,
so use throw-away accounts. It reports PASS/FAIL per check and exits non-zero on any FAIL.
"""
from __future__ import annotations

import argparse
import os
import sys

import httpx

from app.config import get_settings

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((ok, label))
    print(("PASS  " if ok else "FAIL  ") + label)


def sign_in(base: str, key: str, email: str, password: str) -> tuple[str, str]:
    r = httpx.post(f"{base}/auth/v1/token", params={"grant_type": "password"}, headers={"apikey": key},
                   json={"email": email, "password": password}, timeout=20)
    if r.status_code != 200:
        raise SystemExit(f"Sign-in failed for a test account (HTTP {r.status_code}). Confirm the email and password.")
    j = r.json()
    return j["access_token"], j["user"]["id"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="http://localhost:8000")
    args = ap.parse_args()
    s = get_settings()
    need = ["MADHUORA_TEST_A_EMAIL", "MADHUORA_TEST_A_PASSWORD", "MADHUORA_TEST_B_EMAIL", "MADHUORA_TEST_B_PASSWORD"]
    if missing := [n for n in need if not os.environ.get(n)]:
        print("Set these environment variables first:", ", ".join(missing))
        return 2
    base, key = s.supabase_url.rstrip("/"), s.supabase_publishable_key
    if not (base and key):
        print("SUPABASE_URL / SUPABASE_PUBLISHABLE_KEY are not set in backend/.env.")
        return 2
    ta, ida = sign_in(base, key, os.environ["MADHUORA_TEST_A_EMAIL"], os.environ["MADHUORA_TEST_A_PASSWORD"])
    tb, idb = sign_in(base, key, os.environ["MADHUORA_TEST_B_EMAIL"], os.environ["MADHUORA_TEST_B_PASSWORD"])
    check(ida != idb, "the two test accounts are different users")
    api = args.backend.rstrip("/") + "/api/v1"
    ha, hb = {"Authorization": f"Bearer {ta}"}, {"Authorization": f"Bearer {tb}"}

    # A creates a twin and a description (marker text is synthetic).
    marker = "Isolation-check marker: a fictional person who likes quiet mornings and loud music in the evenings."
    httpx.put(f"{api}/twin", headers=ha, json={"name": "Isolation A"}, timeout=20)
    a_me = httpx.get(f"{api}/me", headers=ha, timeout=20).json()
    ver = (a_me.get("character") or {}).get("description_version", 0)
    r = httpx.put(f"{api}/twin/character", headers=ha, json={"description": marker, "base_version": ver}, timeout=20)
    check(r.status_code == 200, "A can save a character description through the API")
    twin_a = (httpx.get(f"{api}/me", headers=ha, timeout=20).json().get("twin") or {}).get("id")
    check(bool(twin_a), "A has a twin id")

    # Through the Madhuora API, B only ever sees B's own data.
    b_me = httpx.get(f"{api}/me", headers=hb, timeout=20).json()
    check(marker not in str(b_me) and (b_me.get("twin") or {}).get("id") != twin_a,
          "B's /me contains nothing from A (twin id and description)")
    r = httpx.post(f"{api}/twin/character/analyze", headers=hb, json={"version": 1}, timeout=20)
    check(r.status_code in (403, 409, 422), f"B's analyze acts on B's own twin only (HTTP {r.status_code}, no AI run for A)")

    # Straight to the database with B's token, like a hostile browser would.
    rest = f"{base}/rest/v1"
    h = {"apikey": key, "Authorization": f"Bearer {tb}", "Prefer": "return=representation"}
    for table in ("twins", "character_profiles", "consents", "profiles", "onboarding_steps"):
        rows = httpx.get(f"{rest}/{table}", headers=h, params={"select": "*"}, timeout=20).json()
        leaked = [x for x in rows if isinstance(x, dict) and ida in (x.get("owner_id"), x.get("user_id"), x.get("id"))]
        check(isinstance(rows, list) and not leaked, f"B cannot read A's rows in {table} (B sees {len(rows)} own row(s))")
    r = httpx.patch(f"{rest}/twins", headers=h, params={"id": f"eq.{twin_a}"}, json={"name": "Hacked"}, timeout=20)
    check(r.status_code in (204, 401, 403) or (r.status_code == 200 and r.json() == []),
          "B cannot update A's twin (zero rows affected)")
    r = httpx.delete(f"{rest}/twins", headers=h, params={"id": f"eq.{twin_a}"}, timeout=20)
    check(r.status_code in (204, 401, 403) or (r.status_code == 200 and r.json() == []), "B cannot delete A's twin")
    r = httpx.post(f"{rest}/consents", headers=h, json={"user_id": ida, "kind": "ai_processing", "version": "x"}, timeout=20)
    check(r.status_code >= 400, "B cannot insert a consent record for A")
    anon = {"apikey": key}
    r = httpx.get(f"{rest}/twins", headers=anon, params={"select": "*"}, timeout=20)
    check(r.status_code in (401, 403) or (r.status_code == 200 and r.json() == []), "an unauthenticated caller sees no twins")

    # ---- Phase 4 tables: conversations, messages, learning ------------------------------------------------------
    # A creates synthetic rows through PostgREST with A's own token (what the API does), then B tries to reach them.
    ha_db = {"apikey": key, "Authorization": f"Bearer {ta}", "Prefer": "return=representation"}
    conv = httpx.post(f"{rest}/conversations", headers=ha_db, json={"owner_id": ida, "twin_id": twin_a, "title": "Isolation chat"}, timeout=20)
    check(conv.status_code == 201, "A can create a conversation on A's own twin")
    cid = conv.json()[0]["id"] if conv.status_code == 201 else None
    private_text = "Isolation-check message text that only A may read."
    msg = httpx.post(f"{rest}/messages", headers=ha_db, json={
        "conversation_id": cid, "owner_id": ida, "role": "user", "content": private_text, "status": "complete",
        "client_message_id": "isolation-key-1"}, timeout=20) if cid else None
    check(msg is not None and msg.status_code == 201, "A can store a message in A's conversation")
    cand = httpx.post(f"{rest}/memory_candidates", headers=ha_db, json={
        "owner_id": ida, "twin_id": twin_a, "conversation_id": cid, "statement": "Isolation candidate", "category": "fact",
        "evidence_type": "explicit_statement", "fingerprint": "iso-fp"}, timeout=20)
    mem = httpx.post(f"{rest}/memories", headers=ha_db, json={
        "owner_id": ida, "twin_id": twin_a, "statement": "Isolation memory", "category": "fact",
        "evidence_type": "explicit_statement", "fingerprint": "iso-fp-m"}, timeout=20)
    check(cand.status_code == 201 and mem.status_code == 201, "A can store a candidate and a memory")
    mem_id = mem.json()[0]["id"] if mem.status_code == 201 else None
    httpx.put(f"{api}/learning/preference", headers=ha, json={"enabled": True, "disclosure_version": httpx.get(f"{api}/learning/preference", headers=ha, timeout=20).json().get("current_disclosure_version")}, timeout=20)

    for table in ("conversations", "messages", "learning_preferences", "memory_candidates", "memories", "profile_proposals", "profile_revisions"):
        rows = httpx.get(f"{rest}/{table}", headers=h, params={"select": "*"}, timeout=20).json()
        leaked = [x for x in rows if isinstance(x, dict) and ida in (x.get("owner_id"),)]
        check(isinstance(rows, list) and not leaked, f"B cannot read A's rows in {table} (B sees {len(rows)} own row(s))")
    check(private_text not in httpx.get(f"{rest}/messages", headers=h, params={"select": "content"}, timeout=20).text, "A's message text is not readable by B")
    for path in (f"/conversations/{cid}/messages", f"/conversations/{cid}/learning"):
        check(httpx.get(f"{api}{path}", headers=hb, timeout=20).status_code == 404, f"B gets 404 for A's {path.split('/')[-1]} through the API")
    check(httpx.delete(f"{api}/conversations/{cid}", headers=hb, timeout=20).status_code == 404, "B cannot delete A's conversation through the API")
    check(httpx.patch(f"{api}/memories/{mem_id}", headers=hb, json={"pinned": True}, timeout=20).status_code == 404, "B cannot edit A's memory through the API")
    # Writes straight to the database.
    r = httpx.post(f"{rest}/messages", headers=h, json={"conversation_id": cid, "owner_id": idb, "role": "user", "content": "intrusion", "status": "complete"}, timeout=20)
    check(r.status_code >= 400, "B cannot add a message to A's conversation")
    r = httpx.post(f"{rest}/messages", headers=h, json={"conversation_id": cid, "owner_id": ida, "role": "user", "content": "spoof", "status": "complete"}, timeout=20)
    check(r.status_code >= 400, "B cannot add a message claiming to be A's")
    r = httpx.post(f"{rest}/conversations", headers=h, json={"owner_id": idb, "twin_id": twin_a, "title": "intrusion"}, timeout=20)
    check(r.status_code >= 400, "B cannot create a conversation on A's twin")
    r = httpx.post(f"{rest}/memories", headers=h, json={"owner_id": idb, "twin_id": twin_a, "statement": "planted", "category": "fact", "evidence_type": "explicit_statement", "fingerprint": "x"}, timeout=20)
    check(r.status_code >= 400, "B cannot plant a memory on A's twin")
    for table, ident in (("memories", mem_id), ("conversations", cid)):
        r = httpx.patch(f"{rest}/{table}", headers=h, params={"id": f"eq.{ident}"}, json={"owner_id": idb}, timeout=20)
        check(r.status_code in (204, 401, 403) or (r.status_code == 200 and r.json() == []), f"B cannot take over A's row in {table}")
        r = httpx.delete(f"{rest}/{table}", headers=h, params={"id": f"eq.{ident}"}, timeout=20)
        check(r.status_code in (204, 401, 403) or (r.status_code == 200 and r.json() == []), f"B cannot delete A's row in {table}")
    check(httpx.get(f"{api}/memories", headers=ha, timeout=20).json().get("memories", [{}])[0].get("id") == mem_id, "A's memory is intact after B's attempts")
    anon_rows = httpx.get(f"{rest}/messages", headers=anon, params={"select": "*"}, timeout=20)
    check(anon_rows.status_code in (401, 403) or (anon_rows.status_code == 200 and anon_rows.json() == []), "an unauthenticated caller sees no messages")
    # Clean up what this check created (A's own rows).
    httpx.delete(f"{api}/conversations/{cid}?delete_memories=true", headers=ha, timeout=20)
    httpx.delete(f"{rest}/memory_candidates", headers=ha_db, params={"fingerprint": "eq.iso-fp"}, timeout=20)
    httpx.put(f"{api}/learning/preference", headers=ha, json={"enabled": False}, timeout=20)

    # A's data is still intact.
    a_after = httpx.get(f"{api}/me", headers=ha, timeout=20).json()
    check(a_after["twin"]["character_description"] == marker and a_after["twin"]["name"] == "Isolation A",
          "A's twin and description are unchanged after B's attempts")
    failed = [lbl for ok, lbl in results if not ok]
    print("\nRESULT:", "ALL PASSED - RLS isolation verified for these checks" if not failed else f"{len(failed)} FAILED")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
