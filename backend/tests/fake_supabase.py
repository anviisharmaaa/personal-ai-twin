"""In-memory stand-in for Supabase PostgREST + Storage used by unit tests.

MOCKED: it approximates RLS (rows visible/writable only to the token's user) so that
route logic can be tested offline. It is NOT evidence that real RLS works; the real
policies are verified against the actual database separately.
"""

import json
import re
from datetime import datetime, timezone
from typing import Any

import httpx

OWNER_COL = {"profiles": "id", "twins": "owner_id", "onboarding_steps": "user_id", "consents": "user_id",
             "character_profiles": "owner_id", "ai_usage": "owner_id", "conversations": "owner_id",
             "messages": "owner_id", "learning_preferences": "owner_id", "memory_candidates": "owner_id",
             "memories": "owner_id", "profile_proposals": "owner_id", "profile_revisions": "owner_id"}
# Column defaults the real database applies (the routes rely on a few of them).
DEFAULTS: dict[str, dict[str, Any]] = {
    "twins": {"kind": "self", "about": None},
    "conversations": {"title": "New conversation", "archived_at": None, "learning_reviewed_at": None},
    "messages": {"content": "", "used_memory_ids": [], "client_message_id": None, "reply_to": None, "provider": None,
                 "model": None, "first_token_ms": None, "duration_ms": None, "failure_code": None},
    "learning_preferences": {"enabled": False, "enabled_at": None, "disabled_at": None, "disclosure_version": None},
    "memory_candidates": {"statement": "", "scope": "", "supporting": [], "status": "pending", "rejected_reason": None,
                          "reviewed_at": None, "conversation_id": None},
    "memories": {"scope": "", "supporting": [], "source_deleted": False, "edited": False, "pinned": False,
                 "status": "active", "superseded_by": None, "candidate_id": None, "conversation_id": None},
    "profile_proposals": {"status": "pending", "current_text": None, "resolved_at": None, "evidence": [],
                          "memory_id": None},
    "profile_revisions": {"proposal_id": None},
}
RESERVED = {"select", "order", "limit", "on_conflict"}


class FakeSupabase:
    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {t: [] for t in OWNER_COL}
        self.objects: dict[str, bytes] = {}
        self.legacy_schema = False      # True: behave like the database BEFORE the multiple-characters migration
        self.calls: list[tuple[str, str, dict[str, str]]] = []
        self._n = 0

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def seed_profile(self, uid: str) -> None:
        self.tables["profiles"].append(
            {"id": uid, "display_name": None, "timezone": "UTC", "deletion_status": "active"}
        )

    @staticmethod
    def _uid(req: httpx.Request) -> str | None:
        auth = req.headers.get("authorization", "")
        m = re.match(r"Bearer token-(.+)", auth)
        return m.group(1) if m else None

    @staticmethod
    def _match(row: dict[str, Any], params: dict[str, str]) -> bool:
        for k, v in params.items():
            if k in RESERVED:
                continue
            if v == "is.null":
                if row.get(k) is not None:
                    return False
            elif v.startswith("eq."):
                if str(row.get(k)) != v[3:]:
                    return False
            elif v.startswith("gte."):
                if row.get(k) is None or str(row.get(k)) < v[4:]:
                    return False
            elif v.startswith("lt."):
                if row.get(k) is None or str(row.get(k)) >= v[3:]:
                    return False
            elif v.startswith("neq."):
                if str(row.get(k)) == v[4:]:
                    return False
            elif v.startswith("in.(") and v.endswith(")"):
                if str(row.get(k)) not in v[4:-1].split(","):
                    return False
        return True

    def _handle(self, req: httpx.Request) -> httpx.Response:
        uid = self._uid(req)
        params = dict(req.url.params)
        path = req.url.path
        self.calls.append((req.method, path, params))
        if uid is None:
            return httpx.Response(401, json={})
        if path.startswith("/rest/v1/"):
            return self._rest(req, uid, path.removeprefix("/rest/v1/"), params)
        if path.startswith("/storage/v1/object/sign/"):
            rest = path.removeprefix("/storage/v1/object/sign/")
            return httpx.Response(200, json={"signedURL": f"/object/sign/{rest}?token=signed"})
        if path.startswith("/storage/v1/object/"):
            return self._storage(req, uid, path.removeprefix("/storage/v1/object/"))
        return httpx.Response(404, json={})

    def _rest(self, req: httpx.Request, uid: str, table: str, params: dict[str, str]) -> httpx.Response:
        col = OWNER_COL[table]
        rows = self.tables[table]
        visible = [r for r in rows if str(r[col]) == uid and self._match(r, params)]
        if req.method == "GET":
            if "order" in params:
                field, _, direction = params["order"].partition(".")
                visible = sorted(visible, key=lambda r: str(r.get(field, "")), reverse=direction == "desc")
            if "limit" in params:
                visible = visible[: int(params["limit"])]
            return httpx.Response(200, json=visible)
        if req.method == "POST":
            body = json.loads(req.content)
            if str(body.get(col)) != uid:
                return httpx.Response(403, json={"code": "42501"})  # RLS violation
            if table == "twins" and self.legacy_schema and (
                    body.get("kind", "self") != "self" or any(str(r[col]) == uid for r in rows)):
                return httpx.Response(409, json={"code": "23505"})      # twins_kind_check / twins_one_per_owner
            if table == "twins":      # kind check; one self per owner; cap
                kind = body.get("kind", "self")
                if kind not in ("self", "character"):
                    return httpx.Response(400, json={"code": "23514"})
                if kind == "self" and any(str(r[col]) == uid and r.get("kind") == "self" for r in rows):
                    return httpx.Response(409, json={"code": "23505"})
                if sum(1 for r in rows if str(r[col]) == uid) >= 25:
                    return httpx.Response(400, json={"code": "23514"})
            if "twin_id" in body and table != "character_profiles" and not any(
                    str(t["id"]) == str(body["twin_id"]) and str(t["owner_id"]) == uid for t in self.tables["twins"]):
                return httpx.Response(403, json={"code": "42501"})   # RLS/FK: only on a twin you own
            if table == "character_profiles" and any(r["twin_id"] == body.get("twin_id") for r in rows):
                return httpx.Response(409, json={"code": "23505"})  # unique(twin_id)
            if table == "onboarding_steps":
                for r in rows:
                    if r["user_id"] == uid and r["step"] == body["step"]:
                        return httpx.Response(201, json=[r])
            if table == "messages" and body.get("role") == "user" and body.get("client_message_id") is not None and any(
                    r["conversation_id"] == body["conversation_id"] and r.get("role") == "user"
                    and r.get("client_message_id") == body["client_message_id"] for r in rows):
                return httpx.Response(409, json={"code": "23505"})  # unique idempotency index
            if table == "messages" and not any(
                    c["id"] == body.get("conversation_id") and str(c["owner_id"]) == uid
                    for c in self.tables["conversations"]):
                return httpx.Response(403, json={"code": "42501"})  # RLS: only inside your own conversation
            if table == "learning_preferences" and any(str(r[col]) == uid for r in rows):
                return httpx.Response(409, json={"code": "23505"})
            self._n += 1
            now = datetime.now(timezone.utc).isoformat()
            row = {"id": f"id-{self._n}", "personality": {}, "communication": {}, "appearance": {},
                   "character_description": "", "character_version": 0, "created_at": now,
                   "portrait_path": None, "portrait_permission_confirmed": False,
                   "granted_at": "2026-10-14T00:00:00Z", "withdrawn_at": None, "last_activity_at": now,
                   **DEFAULTS.get(table, {}), **body}
            rows.append(row)
            return httpx.Response(201, json=[row])
        if req.method == "PATCH":
            body = json.loads(req.content)
            if "owner_id" in body and str(body["owner_id"]) != uid:
                return httpx.Response(403, json={"code": "42501"})  # RLS WITH CHECK
            if table == "twins" and "kind" in body and any(r.get("kind") != body["kind"] for r in visible):
                return httpx.Response(400, json={"code": "23514"})  # twins_guard: kind is immutable
            if table == "conversations" and "twin_id" in body and any(
                    r.get("twin_id") != body["twin_id"] for r in visible):
                return httpx.Response(400, json={"code": "23514"})  # conversations_binding_immutable
            for r in visible:
                r.update(body)
            return httpx.Response(200, json=visible)
        if req.method == "DELETE":
            self.tables[table] = [r for r in rows if r not in visible]
            for gone in visible:
                self._cascade(table, gone["id"])
            return httpx.Response(204)
        return httpx.Response(405)

    def _cascade(self, table: str, row_id: str) -> None:
        """What the foreign keys do in the real schema when a conversation is deleted."""
        if table != "conversations":
            return
        self.tables["messages"] = [m for m in self.tables["messages"] if m["conversation_id"] != row_id]
        for t in ("memory_candidates", "memories"):
            for r in self.tables[t]:
                if r.get("conversation_id") == row_id:
                    r["conversation_id"] = None

    def _storage(self, req: httpx.Request, uid: str, rest: str) -> httpx.Response:
        bucket, _, name = rest.partition("/")
        if not name.startswith(f"{uid}/"):
            return httpx.Response(403, json={})
        key = f"{bucket}/{name}"
        if req.method == "POST":
            self.objects[key] = req.content
            return httpx.Response(200, json={"Key": key})
        if req.method == "DELETE":
            self.objects.pop(key, None)
            return httpx.Response(200, json={})
        return httpx.Response(405)
