import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import AuthUser, current_user
from app.character import MIN_DESCRIPTION_CHARS, SCHEMA_VERSION, AnalysisError, CharacterAnalyzer
from app.character_store import character_view, get_profile_row, qualified_model, sha256, stored_provider
from app.config import get_settings
from app.providers import build_analyzer, consent_version, provider_model
from app.routes import _active_consent, _eq, _twin, _with_portrait_url
from app.schemas import AnalyzeIn, CharacterIn
from app.supabase_rest import SupabaseError, SupabaseRest, get_rest

router = APIRouter(prefix="/api/v1")
log = logging.getLogger("madhuora.character")

# Twins with an analysis in flight in THIS process. Stops double-clicks and duplicate tabs from paying twice.
# (A multi-process deployment would need a database lock instead; noted in the README.)
_in_flight: set[str] = set()


def get_analyzer() -> CharacterAnalyzer:
    """The one explicitly configured provider (AI_PROVIDER). Never falls back to another one."""
    return build_analyzer(get_settings())  # type: ignore[no-any-return]


def _err(code: str, message: str, http: int) -> HTTPException:
    return HTTPException(http, {"code": code, "message": message})


@router.put("/twin/character")
async def save_character(
    body: CharacterIn, user: AuthUser = Depends(current_user), rest: SupabaseRest = Depends(get_rest)
) -> dict[str, Any]:
    twin = await _twin(rest, user)
    if twin is None:
        raise _err("no_twin", "Create your twin's identity first.", status.HTTP_409_CONFLICT)
    current = twin.get("character_description") or ""
    version = int(twin.get("character_version") or 0)
    if body.description != current:
        if body.base_version != version:
            raise _err("changed_elsewhere", "This description changed in another tab or device. "
                       "Reload to see the latest before editing.", status.HTTP_409_CONFLICT)
        rows = await rest.update(
            user.token, "twins",
            # Compare-and-set: only applies if nobody saved a newer version in between.
            {"owner_id": _eq(user.id), "id": _eq(twin["id"]), "character_version": _eq(str(version))},
            {"character_description": body.description, "character_version": version + 1,
             "character_updated_at": datetime.now(timezone.utc).isoformat()},
        )
        if not rows:
            raise _err("changed_elsewhere", "This description changed in another tab or device. "
                       "Reload to see the latest before editing.", status.HTTP_409_CONFLICT)
        twin = rows[0]
    row = await get_profile_row(rest, user, twin["id"])
    return {"twin": await _with_portrait_url(rest, user, twin), "character": character_view(twin, row)}


async def _daily_count(rest: SupabaseRest, user: AuthUser) -> int:
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    rows = await rest.select(
        user.token, "ai_usage",
        {"select": "id", "owner_id": _eq(user.id), "kind": "eq.character_analysis", "created_at": f"gte.{since}"},
    )
    return len(rows)


async def _record_usage(rest: SupabaseRest, user: AuthUser, ok: bool, model: str | None,
                        tin: int | None, tout: int | None, latency_ms: int | None) -> None:
    try:
        await rest.insert(user.token, "ai_usage", {
            "owner_id": user.id, "kind": "character_analysis", "status": "ok" if ok else "error",
            "model": model, "input_tokens": tin, "output_tokens": tout, "latency_ms": latency_ms,
        })
    except SupabaseError:
        log.warning("usage_record_failed")  # never block the user on bookkeeping, never log content


async def _record_failure(rest: SupabaseRest, user: AuthUser, twin_id: str, code: str,
                          row: dict[str, Any] | None) -> None:
    """Only touches the last_failure_* columns, so a previous good profile is never overwritten."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        if row:
            await rest.update(user.token, "character_profiles", {"owner_id": _eq(user.id), "twin_id": _eq(twin_id)},
                              {"last_failure_code": code, "last_failure_at": now, "updated_at": now})
        else:
            await rest.insert(user.token, "character_profiles", {
                "twin_id": twin_id, "owner_id": user.id, "last_failure_code": code, "last_failure_at": now})
    except SupabaseError:
        log.warning("failure_record_failed")


@router.post("/twin/character/analyze")
async def analyze_character(
    body: AnalyzeIn,
    user: AuthUser = Depends(current_user),
    rest: SupabaseRest = Depends(get_rest),
    analyzer: CharacterAnalyzer = Depends(get_analyzer),
) -> dict[str, Any]:
    settings = get_settings()
    twin = await _twin(rest, user)
    if twin is None:
        raise _err("no_twin", "Create your twin's identity first.", status.HTTP_409_CONFLICT)

    # Consent first: nothing personal goes to an external provider without a current, un-withdrawn consent.
    consent = await _active_consent(rest, user)
    if consent is None or consent.get("version") != consent_version(settings):
        raise _err("consent_required", "Please accept AI processing in Settings before analysing a character.",
                   status.HTTP_403_FORBIDDEN)
    if not settings.ai_enabled:
        raise _err("ai_disabled", "AI analysis is temporarily switched off.", status.HTTP_503_SERVICE_UNAVAILABLE)
    if not analyzer.configured:
        raise _err("not_configured", "AI analysis isn't set up on the server yet.", status.HTTP_503_SERVICE_UNAVAILABLE)

    description = twin.get("character_description") or ""
    version = int(twin.get("character_version") or 0)
    if len(description.strip()) < MIN_DESCRIPTION_CHARS:
        raise _err("too_short", f"Write a little more first. Aim for at least {MIN_DESCRIPTION_CHARS} characters.",
                   status.HTTP_422_UNPROCESSABLE_ENTITY)
    if body.version != version:
        raise _err("stale_version", "Your description has changed. Save it, then analyse again.",
                   status.HTTP_409_CONFLICT)

    row = await get_profile_row(rest, user, twin["id"])
    digest = sha256(description)
    provider = getattr(analyzer, "provider", "") or ""
    if row and row.get("profile") is not None and row.get("description_sha256") == digest \
            and row.get("schema_version") == SCHEMA_VERSION and stored_provider(row) == provider:
        # Identical, unchanged description made by the same provider: no new model call. (A profile from a
        # different provider, e.g. a sample, is never reused as if it came from this one.)
        return {"character": character_view(twin, row), "cached": True}

    if twin["id"] in _in_flight:
        raise _err("in_progress", "An analysis is already running.", status.HTTP_409_CONFLICT)
    if await _daily_count(rest, user) >= settings.analysis_daily_limit:
        raise _err("daily_limit", "You've reached today's analysis limit. Please try again tomorrow.",
                   status.HTTP_429_TOO_MANY_REQUESTS)

    _in_flight.add(twin["id"])
    try:
        try:
            result = await analyzer.analyze(description)
        except AnalysisError as exc:
            # Privacy-safe diagnostics only: code, provider and the validator's own detail (positions, field paths,
            # rule names, counts). Never the description, the model's text, a profile or any key.
            log.warning("analysis_failed code=%s provider=%s detail=%s", exc.code, provider, exc.detail or "-")
            await _record_usage(rest, user, False, provider_model(settings), None, None, None)
            await _record_failure(rest, user, twin["id"], exc.code, row)
            raise _err(exc.code, exc.message, exc.status_code) from exc
        await _record_usage(rest, user, True, result.model, result.input_tokens, result.output_tokens,
                            result.latency_ms)

        now = datetime.now(timezone.utc).isoformat()
        fields = {
            "profile": result.profile.model_dump(), "description_version": version, "description_sha256": digest,
            "schema_version": SCHEMA_VERSION, "model": qualified_model(result.provider, result.model),
            "generated_at": now,
            "last_failure_code": None, "last_failure_at": None, "updated_at": now,
        }
        latest = await get_profile_row(rest, user, twin["id"])
        # Never replace a profile that was made from a newer description than this one.
        if latest and (latest.get("description_version") or 0) > version:
            pass
        elif latest:
            await rest.update(user.token, "character_profiles",
                              {"owner_id": _eq(user.id), "twin_id": _eq(twin["id"])}, fields)
        else:
            await rest.insert(user.token, "character_profiles",
                              {"twin_id": twin["id"], "owner_id": user.id, **fields})
    finally:
        _in_flight.discard(twin["id"])

    # Re-read so a description that changed *during* generation shows this profile as outdated, not current.
    fresh_twin = await _twin(rest, user) or twin
    return {"character": character_view(fresh_twin, await get_profile_row(rest, user, twin["id"])), "cached": False}
