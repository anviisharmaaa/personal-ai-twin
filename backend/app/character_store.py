"""Reading the stored character state and shaping it for the client."""

import hashlib
from datetime import datetime
from typing import Any

from app.auth import AuthUser
from app.character import MIN_DESCRIPTION_CHARS
from app.supabase_rest import SupabaseRest


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


async def get_profile_row(rest: SupabaseRest, user: AuthUser, twin_id: str) -> dict[str, Any] | None:
    rows = await rest.select(
        user.token, "character_profiles",
        {"select": "*", "owner_id": f"eq.{user.id}", "twin_id": f"eq.{twin_id}"},
    )
    return rows[0] if rows else None


def character_view(twin: dict[str, Any], row: dict[str, Any] | None) -> dict[str, Any]:
    """What the client needs: status, the profile (if any) and whether it matches the current description.

    status:
      empty        no description yet
      not_analysed description saved, never analysed
      current      the profile was made from the description as it is now
      outdated     the description changed after the profile was made
    `failure` is set only when the most recent attempt failed *after* the last good profile; the last
    good profile is still returned (and still marked outdated/current honestly).
    """
    description = twin.get("character_description") or ""
    version = int(twin.get("character_version") or 0)
    profile = row.get("profile") if row else None
    if not description.strip():
        status = "empty"
    elif profile is None:
        status = "not_analysed"
    elif row and row.get("description_version") == version:
        status = "current"
    else:
        status = "outdated"
    failure = None
    if row and row.get("last_failure_code"):
        failed_at, made_at = _ts(row.get("last_failure_at")), _ts(row.get("generated_at"))
        if failed_at and (made_at is None or failed_at > made_at):
            failure = row["last_failure_code"]
    return {
        "status": status,
        "description_version": version,
        "min_chars": MIN_DESCRIPTION_CHARS,
        "profile": profile,
        "profile_version": row.get("description_version") if row and profile is not None else None,
        "generated_at": row.get("generated_at") if row and profile is not None else None,
        "failure": failure,
    }
