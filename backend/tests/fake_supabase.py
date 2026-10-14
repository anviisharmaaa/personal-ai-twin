"""In-memory stand-in for Supabase PostgREST + Storage used by unit tests.

MOCKED: it approximates RLS (rows visible/writable only to the token's user) so that
route logic can be tested offline. It is NOT evidence that real RLS works; the real
policies are verified against the actual database separately.
"""

import json
import re
from typing import Any

import httpx

OWNER_COL = {"profiles": "id", "twins": "owner_id", "onboarding_steps": "user_id", "consents": "user_id"}
RESERVED = {"select", "order", "limit", "on_conflict"}


class FakeSupabase:
    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {t: [] for t in OWNER_COL}
        self.objects: dict[str, bytes] = {}
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
            return httpx.Response(200, json=visible)
        if req.method == "POST":
            body = json.loads(req.content)
            if str(body.get(col)) != uid:
                return httpx.Response(403, json={"code": "42501"})  # RLS violation
            if table == "twins" and any(str(r[col]) == uid for r in rows):
                return httpx.Response(409, json={"code": "23505"})
            if table == "onboarding_steps":
                for r in rows:
                    if r["user_id"] == uid and r["step"] == body["step"]:
                        return httpx.Response(201, json=[r])
            self._n += 1
            row = {"id": f"id-{self._n}", "personality": {}, "communication": {}, "appearance": {},
                   "portrait_path": None, "portrait_permission_confirmed": False,
                   "granted_at": "2026-10-14T00:00:00Z", "withdrawn_at": None, **body}
            rows.append(row)
            return httpx.Response(201, json=[row])
        if req.method == "PATCH":
            body = json.loads(req.content)
            for r in visible:
                r.update(body)
            return httpx.Response(200, json=visible)
        if req.method == "DELETE":
            self.tables[table] = [r for r in rows if r not in visible]
            return httpx.Response(204)
        return httpx.Response(405)

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
