"""LIVE cross-user isolation check against your DEVELOPMENT Supabase project. Not part of the mocked tests.

Needs two separate development accounts (A and B). A must already have a twin (finish onboarding as A first).
Run from the backend folder:  python -m scripts.rls_two_user_check

Emails/passwords are asked for interactively (passwords are not echoed or stored). Nothing is printed except
PASS/FAIL lines. The check is deliberately non-destructive: it never issues a DELETE against A's data, and its
only write attempts are ones that must be rejected. If a write unexpectedly succeeds, it says so and tells you
exactly what to clean up.
"""

import getpass
import sys

import httpx

from app.config import get_settings

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6300010000000500010d0a2db40000000049454e44ae426082"
)
results: list[tuple[bool, str]] = []


def record(ok: bool, what: str) -> None:
    results.append((ok, what))
    print(f"  [{'PASS' if ok else 'FAIL'}] {what}")


def sign_in(c: httpx.Client, base: str, key: str, label: str) -> tuple[str, str]:
    email = input(f"Account {label} email: ").strip()
    pw = getpass.getpass(f"Account {label} password: ")
    r = c.post(f"{base}/auth/v1/token", params={"grant_type": "password"}, headers={"apikey": key},
               json={"email": email, "password": pw})
    if r.status_code != 200:
        print(f"Could not sign in as {label} (HTTP {r.status_code}).")
        sys.exit(2)
    body = r.json()
    return body["access_token"], body["user"]["id"]


def main() -> int:
    s = get_settings()
    base, key = s.supabase_url.rstrip("/"), s.supabase_publishable_key
    if not (base and key):
        print("SUPABASE_URL / SUPABASE_PUBLISHABLE_KEY missing in backend/.env")
        return 2
    with httpx.Client(timeout=20) as c:
        ta, ua = sign_in(c, base, key, "A")
        tb, ub = sign_in(c, base, key, "B")
        if ua == ub:
            print("A and B are the same account. Use two different accounts.")
            return 2

        def h(tok: str) -> dict[str, str]:
            return {"apikey": key, "Authorization": f"Bearer {tok}"}

        twin = c.get(f"{base}/rest/v1/twins", headers=h(ta), params={"select": "id,about,portrait_path", "owner_id": f"eq.{ua}"}).json()
        if not twin:
            print("Account A has no twin yet. Complete onboarding as A, then re-run.")
            return 2
        tid, about, portrait = twin[0]["id"], twin[0]["about"], twin[0]["portrait_path"]
        print("\nAs B, trying to read A's data (every result must be empty):")
        tables = {"twins": "owner_id", "profiles": "id", "onboarding_steps": "user_id", "consents": "user_id",
                  "character_profiles": "owner_id", "ai_usage": "owner_id"}
        for t, col in tables.items():
            r = c.get(f"{base}/rest/v1/{t}", headers=h(tb), params={"select": "*", col: f"eq.{ua}"})
            record(r.status_code == 200 and r.json() == [], f"B cannot read A's rows in {t} (HTTP {r.status_code}, {len(r.json()) if r.status_code == 200 else '-'} rows)")
        r = c.get(f"{base}/rest/v1/twins", headers=h(tb), params={"select": "id", "id": f"eq.{tid}"})
        record(r.status_code == 200 and r.json() == [], "B cannot read A's twin by id")

        print("\nAs B, trying to write to A's data (all must be blocked):")
        r = c.patch(f"{base}/rest/v1/twins", headers={**h(tb), "Prefer": "return=representation"}, params={"id": f"eq.{tid}"}, json={"about": about})
        record(r.status_code in (200, 204) and (r.status_code == 204 or r.json() == []), f"B updating A's twin changes 0 rows (HTTP {r.status_code}; same-value write, safe)")
        for t, body in {
            "ai_usage": {"owner_id": ua, "kind": "character_analysis", "status": "ok"},
            "character_profiles": {"twin_id": tid, "owner_id": ua},
            "character_profiles ": {"twin_id": tid, "owner_id": ub},
            "twins": {"owner_id": ua, "kind": "self", "name": "rls-check"},
        }.items():
            r = c.post(f"{base}/rest/v1/{t.strip()}", headers={**h(tb), "Prefer": "return=representation"}, json=body)
            ok = r.status_code in (401, 403, 409)
            record(ok, f"B inserting into {t.strip()} on A's behalf is rejected (HTTP {r.status_code})")
            if r.status_code in (200, 201):
                print(f"      !! A row was created. Remove it manually in the dashboard: table {t.strip()}, body {r.text[:200]}")

        print("\nStorage (portraits bucket):")
        r = c.post(f"{base}/storage/v1/object/list/portraits", headers=h(tb), json={"prefix": f"{ua}/", "limit": 10})
        record(r.status_code == 200 and r.json() == [] or r.status_code in (400, 401, 403), f"B listing A's folder sees nothing (HTTP {r.status_code})")
        if portrait:
            r = c.get(f"{base}/storage/v1/object/authenticated/portraits/{portrait}", headers=h(tb))
            record(r.status_code in (400, 401, 403, 404), f"B cannot download A's portrait (HTTP {r.status_code})")
        else:
            print("  (A has no portrait; download check skipped. Upload one as A for a stronger test.)")
        r = c.post(f"{base}/storage/v1/object/portraits/{ua}/rls-check.png", headers={**h(tb), "Content-Type": "image/png", "x-upsert": "false"}, content=PNG)
        record(r.status_code in (400, 401, 403), f"B cannot upload into A's folder (HTTP {r.status_code})")
        if r.status_code == 200:
            c.delete(f"{base}/storage/v1/object/portraits/{ua}/rls-check.png", headers=h(tb))
            print("      !! The upload succeeded and was deleted again.")

        print("\nSigned-out (publishable key only):")
        r = c.get(f"{base}/rest/v1/twins", headers={"apikey": key}, params={"select": "id"})
        record(r.status_code in (401, 403) or r.json() == [], f"anonymous access to twins returns nothing (HTTP {r.status_code})")

        print("\nNot tested on purpose: DELETE on A's rows (a failure would destroy data).")
    failed = [w for ok, w in results if not ok]
    print("\nRESULT:", "ALL CHECKS PASSED" if not failed else f"{len(failed)} FAILED -> do NOT treat RLS as verified")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
