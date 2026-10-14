import struct
import zlib

from fastapi.testclient import TestClient

from tests.conftest import auth
from tests.fake_supabase import FakeSupabase

CONSENT = "2026-10-v3-none"  # tests run with AI_PROVIDER unset; the version is provider-specific


def png_bytes() -> bytes:
    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    raw = b"\x00\xff\x00\x00"
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def test_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/me").status_code == 401
    assert client.get("/api/v1/me", headers={"Authorization": "Bearer garbage"}).status_code == 401
    assert client.put("/api/v1/twin", json={"name": "x"}).status_code == 401


def test_me_for_new_user(client: TestClient) -> None:
    body = client.get("/api/v1/me", headers=auth("alice")).json()
    assert body["twin"] is None and body["completed_steps"] == []
    assert body["ai_consent"]["granted"] is False


def test_welcome_requires_real_consent(client: TestClient) -> None:
    h = auth("alice")
    assert client.post("/api/v1/onboarding/steps/welcome/complete", headers=h).status_code == 409
    assert client.post("/api/v1/consents/ai-processing", json={"version": "old"}, headers=h).status_code == 409
    assert client.post("/api/v1/consents/ai-processing", json={"version": CONSENT}, headers=h).status_code == 201
    assert client.post("/api/v1/onboarding/steps/welcome/complete", headers=h).status_code == 200
    assert client.get("/api/v1/me", headers=h).json()["completed_steps"] == ["welcome"]
    client.delete("/api/v1/consents/ai-processing", headers=h)
    assert client.get("/api/v1/me", headers=h).json()["ai_consent"]["granted"] is False


def test_identity_flow(client: TestClient) -> None:
    h = auth("alice")
    assert client.post("/api/v1/onboarding/steps/identity/complete", headers=h).status_code == 409
    assert client.put("/api/v1/twin", json={"about": "hi"}, headers=h).status_code == 422
    r = client.put("/api/v1/twin", json={"name": "Anvi", "appearance": {"framing": "close"}}, headers=h)
    assert r.status_code == 200 and r.json()["name"] == "Anvi"
    r = client.put("/api/v1/twin", json={"appearance": {"lighting": "warm"}}, headers=h)
    assert r.json()["appearance"] == {"framing": "close", "lighting": "warm"}  # merged, not replaced
    assert client.post("/api/v1/onboarding/steps/identity/complete", headers=h).status_code == 200
    # The old questionnaire endpoints are gone, and the old "communication" field is no longer accepted.
    assert client.get("/api/v1/onboarding/questionnaire", headers=h).status_code == 404
    assert client.put("/api/v1/twin/personality", json={"answers": {}}, headers=h).status_code in (404, 405)
    assert client.put("/api/v1/twin", json={"communication": {"emoji": "never"}}, headers=h).status_code == 422


def test_unavailable_steps_cannot_be_marked(client: TestClient) -> None:
    for s in ("memory_import", "memory_review", "first_chat"):
        assert client.post(f"/api/v1/onboarding/steps/{s}/complete", headers=auth("alice")).status_code == 409


def test_strict_inputs(client: TestClient) -> None:
    h = auth("alice")
    assert client.put("/api/v1/me/profile", json={"id": "bob"}, headers=h).status_code == 422
    assert client.put("/api/v1/twin", json={"name": "A", "owner_id": "bob"}, headers=h).status_code == 422
    assert client.post("/api/v1/onboarding/steps/bogus/complete", headers=h).status_code == 422


def test_users_are_isolated_and_filters_always_sent(client: TestClient, fake: FakeSupabase) -> None:
    client.put("/api/v1/twin", json={"name": "Alice twin"}, headers=auth("alice"))
    bob = client.get("/api/v1/me", headers=auth("bob")).json()
    assert bob["twin"] is None
    client.put("/api/v1/twin", json={"name": "Bob twin"}, headers=auth("bob"))
    assert [t["name"] for t in fake.tables["twins"] if t["owner_id"] == "alice"] == ["Alice twin"]
    for method, path, params in fake.calls:
        if path == "/rest/v1/twins" and method in ("GET", "PATCH"):
            assert params["owner_id"] in ("eq.alice", "eq.bob")  # explicit ownership filter, besides RLS


def test_portrait_rules(client: TestClient, fake: FakeSupabase) -> None:
    h = auth("alice")
    files = {"file": ("p.png", png_bytes(), "image/png")}
    assert client.post("/api/v1/twin/portrait", files=files, headers=h).status_code == 409  # no twin yet
    client.put("/api/v1/twin", json={"name": "A"}, headers=h)
    assert client.post("/api/v1/twin/portrait", files={"file": ("p.png", b"GIF89a....", "image/png")},
                       headers=h).status_code == 415  # content-type lies
    big = b"\x89PNG\r\n\x1a\n" + b"0" * (5 * 1024 * 1024)
    assert client.post("/api/v1/twin/portrait", files={"file": ("p.png", big, "image/png")},
                       headers=h).status_code == 413
    other = client.post("/api/v1/twin/portrait", files=files, data={"depicts_someone_else": "true"}, headers=h)
    assert other.status_code == 422
    ok = client.post("/api/v1/twin/portrait", files=files, headers=h)
    assert ok.status_code == 200
    body = ok.json()
    assert body["portrait_path"].startswith("alice/") and body["portrait_url"]
    first = body["portrait_path"]
    again = client.post("/api/v1/twin/portrait", files=files,
                        data={"depicts_someone_else": "true", "permission_confirmed": "true"}, headers=h).json()
    assert again["portrait_permission_confirmed"] is True and again["portrait_path"] != first
    assert f"portraits/{first}" not in fake.objects  # replaced file was cleaned up
    assert client.delete("/api/v1/twin/portrait", headers=h).status_code == 204
    assert not [k for k in fake.objects if k.startswith("portraits/alice/")]
    assert client.get("/api/v1/me", headers=h).json()["twin"]["portrait_url"] is None


def test_never_signs_a_path_outside_own_folder(client: TestClient, fake: FakeSupabase) -> None:
    client.put("/api/v1/twin", json={"name": "A"}, headers=auth("alice"))
    fake.tables["twins"][0]["portrait_path"] = "bob/secret.png"  # simulates tampered data
    assert client.get("/api/v1/me", headers=auth("alice")).json()["twin"]["portrait_url"] is None


def test_health_and_ready(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}
    assert all(isinstance(v, bool) for v in client.get("/ready").json()["configured"].values())
