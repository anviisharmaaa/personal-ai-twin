"""Thin Supabase client that always acts AS THE USER (user JWT), so RLS applies in
addition to the explicit ownership filters the routes add."""

from functools import lru_cache
from typing import Any

import httpx
from fastapi import HTTPException, status

from app.config import get_settings


class SupabaseError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"supabase error {status_code}")
        self.status_code = status_code


class SupabaseRest:
    def __init__(self, base_url: str, apikey: str, transport: httpx.AsyncBaseTransport | None = None):
        self._base = base_url.rstrip("/")
        self._apikey = apikey
        self._transport = transport

    def _client(self, token: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base,
            transport=self._transport,
            timeout=httpx.Timeout(10.0),
            headers={"apikey": self._apikey, "Authorization": f"Bearer {token}"},
        )

    @staticmethod
    def _check(r: httpx.Response) -> None:
        if r.status_code >= 400:
            raise SupabaseError(r.status_code)

    async def select(self, token: str, table: str, params: dict[str, str]) -> list[dict[str, Any]]:
        async with self._client(token) as c:
            r = await c.get(f"/rest/v1/{table}", params=params)
        self._check(r)
        data: list[dict[str, Any]] = r.json()
        return data

    async def insert(
        self, token: str, table: str, body: dict[str, Any], *, upsert_on: str | None = None
    ) -> dict[str, Any]:
        prefer = "return=representation"
        params: dict[str, str] = {}
        if upsert_on:
            prefer += ",resolution=merge-duplicates"
            params["on_conflict"] = upsert_on
        async with self._client(token) as c:
            r = await c.post(f"/rest/v1/{table}", json=body, params=params, headers={"Prefer": prefer})
        self._check(r)
        rows: list[dict[str, Any]] = r.json()
        return rows[0]

    async def update(
        self, token: str, table: str, params: dict[str, str], body: dict[str, Any]
    ) -> list[dict[str, Any]]:
        async with self._client(token) as c:
            r = await c.patch(
                f"/rest/v1/{table}", params=params, json=body, headers={"Prefer": "return=representation"}
            )
        self._check(r)
        rows: list[dict[str, Any]] = r.json()
        return rows

    async def delete(self, token: str, table: str, params: dict[str, str]) -> None:
        async with self._client(token) as c:
            r = await c.delete(f"/rest/v1/{table}", params=params)
        self._check(r)

    async def upload_object(
        self, token: str, bucket: str, path: str, content: bytes, content_type: str
    ) -> None:
        async with self._client(token) as c:
            r = await c.post(
                f"/storage/v1/object/{bucket}/{path}",
                content=content,
                headers={"Content-Type": content_type, "x-upsert": "false"},
            )
        self._check(r)

    async def delete_object(self, token: str, bucket: str, path: str) -> None:
        async with self._client(token) as c:
            r = await c.delete(f"/storage/v1/object/{bucket}/{path}")
        if r.status_code not in (200, 204, 404):
            raise SupabaseError(r.status_code)

    async def sign_object(self, token: str, bucket: str, path: str, expires_in: int = 3600) -> str:
        async with self._client(token) as c:
            r = await c.post(f"/storage/v1/object/sign/{bucket}/{path}", json={"expiresIn": expires_in})
        self._check(r)
        return f"{self._base}/storage/v1{r.json()['signedURL']}"


@lru_cache
def _cached_rest() -> SupabaseRest:
    s = get_settings()
    return SupabaseRest(s.supabase_url, s.supabase_publishable_key)


def get_rest() -> SupabaseRest:
    if not get_settings().supabase_url:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Data service is not configured.")
    return _cached_rest()
