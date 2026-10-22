from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.auth import TokenVerifier, get_verifier
from app.config import Settings, get_settings
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


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Mocked tests never see the developer's real configuration.

    Settings normally reads backend/.env (and the process environment). That is right for the running app and wrong for
    tests: a developer's AI_PROVIDER/NVIDIA_API_KEY would change provider selection, consent versions and "not
    configured" cases. So for every test: (1) the .env file is switched off, (2) every Settings variable is removed from
    the process environment, (3) the settings cache is cleared before and after. Tests that need a provider set it
    explicitly with monkeypatch.setenv(...) followed by get_settings.cache_clear(). Production code is not touched.
    """
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    # Chat defaults to NVIDIA in production config; mocked tests start with chat OFF and opt in explicitly.
    monkeypatch.setenv("CHAT_PROVIDER", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


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
