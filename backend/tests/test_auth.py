import time

import jwt
import pytest
from fastapi import HTTPException

from app.auth import TokenVerifier
from app.config import Settings

URL = "https://proj.supabase.co"
SECRET = "unit-test-secret-which-is-long-enough-32b"  # noqa: S105


def verifier() -> TokenVerifier:
    return TokenVerifier(Settings(supabase_url=URL, supabase_jwt_secret=SECRET))


def make(**over: object) -> str:
    claims = {"sub": "u1", "aud": "authenticated", "iss": f"{URL}/auth/v1", "exp": int(time.time()) + 600}
    claims.update(over)
    return jwt.encode(claims, SECRET, algorithm="HS256")


def test_valid_token() -> None:
    assert verifier().verify(make())["sub"] == "u1"


@pytest.mark.parametrize(
    "token",
    [
        make(exp=int(time.time()) - 10),
        make(aud="anon"),
        make(iss="https://evil.example/auth/v1"),
        jwt.encode({"sub": "u1", "aud": "authenticated", "iss": f"{URL}/auth/v1", "exp": 9999999999},
                   "wrong-secret-wrong-secret-wrong-1234", algorithm="HS256"),
        "not-a-jwt",
    ],
)
def test_bad_tokens_rejected(token: str) -> None:
    with pytest.raises(HTTPException) as e:
        verifier().verify(token)
    assert e.value.status_code == 401


def test_alg_none_rejected() -> None:
    token = jwt.encode({"sub": "u1", "aud": "authenticated", "iss": f"{URL}/auth/v1", "exp": 9999999999},
                       None, algorithm="none")  # type: ignore[arg-type]
    with pytest.raises(HTTPException) as e:
        verifier().verify(token)
    assert e.value.status_code == 401


def test_missing_sub_rejected() -> None:
    claims = {"aud": "authenticated", "iss": f"{URL}/auth/v1", "exp": int(time.time()) + 60}
    with pytest.raises(HTTPException):
        verifier().verify(jwt.encode(claims, SECRET, algorithm="HS256"))


def test_unconfigured_is_503() -> None:
    with pytest.raises(HTTPException) as e:
        TokenVerifier(Settings(supabase_url="")).verify("x")
    assert e.value.status_code == 503
