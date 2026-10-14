from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_ready_never_leaks_values() -> None:
    r = client.get("/ready")
    assert r.status_code == 200
    assert all(isinstance(v, bool) for v in r.json()["configured"].values())
