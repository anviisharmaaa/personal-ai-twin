"""Test helper for the asynchronous analysis endpoint.

POST /twin/character/analyze answers 202 at once and finishes the work in the background (TestClient runs background
tasks before returning). `analyze` posts, then reads /me, and presents the finished outcome in the old synchronous
shape so assertions stay about behaviour. Synchronous refusals (403, 409, 422, 429, 503 ...) are returned untouched.
"""
import httpx
from fastapi.testclient import TestClient

_STATUS = {"timeout": 504, "rate_limited": 429, "quota_exhausted": 503, "local_unavailable": 503,
           "local_model_missing": 503, "provider_error": 502}


def analyze(client: TestClient, headers: dict[str, str], version: int) -> httpx.Response:
    r = client.post("/api/v1/twin/character/analyze", json={"version": version}, headers=headers)
    if r.status_code != 202:
        return r
    assert r.json()["character"]["analysis"]["state"] == "running"
    character = client.get("/api/v1/me", headers=headers).json()["character"]
    assert character["analysis"]["state"] == "idle", "the background job must have finished"
    if character["failure"]:
        code = character["failure"]
        return httpx.Response(_STATUS.get(code, 502), json={"detail": {"code": code, "message": ""}})
    return httpx.Response(200, json={"character": character, "cached": False})
