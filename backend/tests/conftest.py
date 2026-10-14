from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.auth import TokenVerifier, get_verifier
from app.main import app
from app.supabase_rest import SupabaseRest, get_rest
from tests.fake_supabase import FakeSupabase


class FakeVerifier(TokenVerifier):
    def __init__(self) -> None:  # noqa: D107 - skip real settings
        pass

    def verify(self, token: str) -> dict[str, Any]:
        from fastapi import HTTPException

        if not token.startswith("token-"):
            raise HTTPException(401, "Invalid or expired session.")
        return {"sub": token.removeprefix("token-")}


@pytest.fixture
def fake() -> FakeSupabase:
    f = FakeSupabase()
    f.seed_profile("alice")
    f.seed_profile("bob")
    return f


@pytest.fixture
def client(fake: FakeSupabase) -> Iterator[TestClient]:
    app.dependency_overrides[get_verifier] = lambda: FakeVerifier()
    app.dependency_overrides[get_rest] = lambda: SupabaseRest("http://sb.test", "pk", transport=fake.transport())
    yield TestClient(app)
    app.dependency_overrides.clear()


def auth(user: str) -> dict[str, str]:
    return {"Authorization": f"Bearer token-{user}"}
