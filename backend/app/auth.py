"""Server-side token validation. User identity comes ONLY from verified claims."""

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import jwt
from fastapi import Depends, Header, HTTPException, status
from jwt import PyJWKClient

from app.config import Settings, get_settings


@dataclass(frozen=True)
class AuthUser:
    id: str
    token: str


def _unauthorized() -> HTTPException:
    # Deliberately generic: never reveal why a token failed.
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Invalid or expired session.",
        headers={"WWW-Authenticate": "Bearer"},
    )


class TokenVerifier:
    def __init__(self, settings: Settings) -> None:
        self._url = settings.supabase_url.rstrip("/")
        self._secret = settings.supabase_jwt_secret
        self._jwks: PyJWKClient | None = None

    def _jwk_client(self) -> PyJWKClient:
        if self._jwks is None:
            self._jwks = PyJWKClient(f"{self._url}/auth/v1/.well-known/jwks.json", cache_keys=True)
        return self._jwks

    def verify(self, token: str) -> dict[str, Any]:
        if not self._url:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Auth is not configured.")
        try:
            alg = jwt.get_unverified_header(token).get("alg")
            key: Any
            if alg == "HS256" and self._secret:
                key = self._secret
            elif alg in ("ES256", "RS256"):
                key = self._jwk_client().get_signing_key_from_jwt(token).key
            else:
                raise _unauthorized()
            claims: dict[str, Any] = jwt.decode(
                token,
                key,
                algorithms=[alg],
                audience="authenticated",
                issuer=f"{self._url}/auth/v1",
                options={"require": ["exp", "sub", "aud", "iss"]},
            )
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 - any failure is a 401
            raise _unauthorized() from exc
        return claims


@lru_cache
def _cached_verifier() -> TokenVerifier:
    return TokenVerifier(get_settings())


def get_verifier() -> TokenVerifier:
    return _cached_verifier()


def current_user(
    authorization: str | None = Header(default=None),
    verifier: TokenVerifier = Depends(get_verifier),
) -> AuthUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _unauthorized()
    token = authorization[7:].strip()
    claims = verifier.verify(token)
    return AuthUser(id=str(claims["sub"]), token=token)
