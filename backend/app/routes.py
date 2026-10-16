import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status

from app.auth import AuthUser, current_user
from app.character_store import character_view, get_profile_row
from app.config import get_settings
from app.providers import consent_version, provider_info
from app.schemas import CharacterCreateIn, ConsentIn, OnboardingStep, ProfileIn, TwinIn
from app.supabase_rest import SupabaseError, SupabaseRest, get_rest

USER_IDENTITY_FIELDS = {"user_gender", "user_gender_custom", "user_pronouns", "user_address_form"}
router = APIRouter(prefix="/api/v1")
log = logging.getLogger("madhuora.api")

# Consent text and version are provider-specific (see app.providers.consent_version).
BUCKET = "portraits"
MAX_PORTRAIT_BYTES = 5 * 1024 * 1024
UNAVAILABLE_STEPS = {
    "memory_import": "Memory import arrives in a later release.",
    "memory_review": "Memory review arrives in a later release.",
    "first_chat": "Chat is not available yet.",
}


def _eq(value: str) -> str:
    return f"eq.{value}"


def _sniff(data: bytes) -> tuple[str, str] | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    return None


MAX_CHARACTERS = 25          # per account; the database enforces the same cap (twins_guard trigger)
_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")     # no PostgREST metacharacters ever reach a query


def character_error(code: str, message: str, http: int) -> HTTPException:
    return HTTPException(http, {"code": code, "message": message})


async def _twin(rest: SupabaseRest, user: AuthUser) -> dict[str, Any] | None:
    """The user's personal self-twin (at most one). Other characters are reached only by an explicit, verified id."""
    rows = await rest.select(user.token, "twins", {"select": "*", "owner_id": _eq(user.id), "kind": "eq.self",
                                                   "limit": "1"})
    return rows[0] if rows else None


async def owned_character(rest: SupabaseRest, user: AuthUser, character_id: str) -> dict[str, Any]:
    """A character id from the browser is only a request: it must be one of the signed-in user's own (404 otherwise;
    the same answer for 'does not exist' and 'belongs to someone else', so ids cannot be probed)."""
    if not _ID.match(character_id):
        raise character_error("character_not_found", "That character doesn't exist.", status.HTTP_404_NOT_FOUND)
    rows = await rest.select(user.token, "twins", {"select": "*", "id": _eq(character_id), "owner_id": _eq(user.id)})
    if not rows:
        raise character_error("character_not_found", "That character doesn't exist.", status.HTTP_404_NOT_FOUND)
    return rows[0]


async def target_twin(rest: SupabaseRest, user: AuthUser, character_id: str | None) -> dict[str, Any] | None:
    """The character an endpoint acts on: the named one (verified), or the self-twin when none is named."""
    return await owned_character(rest, user, character_id) if character_id else await _twin(rest, user)


async def _with_portrait_url(rest: SupabaseRest, user: AuthUser, twin: dict[str, Any]) -> dict[str, Any]:
    out = dict(twin)
    out["portrait_url"] = None
    path = twin.get("portrait_path")
    # Only ever sign a path inside the caller's own folder.
    if path and path.startswith(f"{user.id}/"):
        try:
            out["portrait_url"] = await rest.sign_object(user.token, BUCKET, path, 3600)
        except SupabaseError:
            out["portrait_url"] = None
    return out


async def _active_consent(rest: SupabaseRest, user: AuthUser) -> dict[str, Any] | None:
    rows = await rest.select(
        user.token,
        "consents",
        {"select": "*", "user_id": _eq(user.id), "kind": "eq.ai_processing",
         "withdrawn_at": "is.null", "order": "granted_at.desc", "limit": "1"},
    )
    return rows[0] if rows else None


@router.get("/me")
async def me(user: AuthUser = Depends(current_user), rest: SupabaseRest = Depends(get_rest)) -> dict[str, Any]:
    profile, twin, steps, consent = await asyncio.gather(
        rest.select(user.token, "profiles", {"select": "*", "id": _eq(user.id)}),
        _twin(rest, user),
        rest.select(user.token, "onboarding_steps", {"select": "step,completed_at", "user_id": _eq(user.id)}),
        _active_consent(rest, user),
    )
    row = await get_profile_row(rest, user, twin["id"]) if twin else None
    cv = consent_version(get_settings())
    return {
        "user_id": user.id,
        "profile": profile[0] if profile else None,
        "twin": await _with_portrait_url(rest, user, twin) if twin else None,
        "character": character_view(twin, row) if twin else None,
        "completed_steps": sorted(s["step"] for s in steps),
        # Only a consent to the *current* wording counts. An older version must be re-accepted.
        "ai_consent": {"granted": bool(consent and consent["version"] == cv),
                       "version": consent["version"] if consent else None,
                       "current_version": cv,
                       "provider": provider_info(get_settings())},
    }


@router.put("/me/profile")
async def update_profile(
    body: ProfileIn, user: AuthUser = Depends(current_user), rest: SupabaseRest = Depends(get_rest)
) -> dict[str, Any]:
    sent = body.model_dump(exclude_unset=True)
    # display_name/timezone cannot be cleared (as before); identity fields can (explicit null = not specified).
    patch = {k: v for k, v in sent.items() if v is not None or k in USER_IDENTITY_FIELDS}
    if not patch:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Nothing to update.")
    for k in ("user_gender_custom", "user_pronouns"):
        if isinstance(patch.get(k), str):
            patch[k] = " ".join(patch[k].split()) or None
    if "user_gender" in patch and patch["user_gender"] != "other":
        patch["user_gender_custom"] = None            # custom wording only belongs to "Other / custom"
    try:
        rows = await rest.update(user.token, "profiles", {"id": _eq(user.id)}, patch)
    except SupabaseError as exc:
        if exc.status_code == 400 and USER_IDENTITY_FIELDS & patch.keys():
            log.warning("user_identity_columns_missing: apply migration 20261016100000_user_identity")
            raise character_error("migration_required", "The database hasn't been upgraded to store this yet. Apply "
                                  "the latest migration (20261016100000_user_identity) and try again.",
                                  status.HTTP_503_SERVICE_UNAVAILABLE) from exc
        raise
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profile not found.")
    return rows[0]


@router.post("/consents/ai-processing", status_code=status.HTTP_201_CREATED)
async def grant_ai_consent(
    body: ConsentIn, user: AuthUser = Depends(current_user), rest: SupabaseRest = Depends(get_rest)
) -> dict[str, Any]:
    cv = consent_version(get_settings())
    if body.version != cv:
        raise HTTPException(status.HTTP_409_CONFLICT, "Consent text has changed; please review it again.")
    existing = await _active_consent(rest, user)
    if existing and existing["version"] == cv:
        return existing
    if existing:
        # Agreeing to new wording (or a different AI provider) supersedes the older agreement.
        await rest.update(
            user.token, "consents",
            {"user_id": _eq(user.id), "kind": "eq.ai_processing", "withdrawn_at": "is.null"},
            {"withdrawn_at": datetime.now(timezone.utc).isoformat()},
        )
    return await rest.insert(
        user.token, "consents", {"user_id": user.id, "kind": "ai_processing", "version": body.version}
    )


@router.delete("/consents/ai-processing", status_code=status.HTTP_204_NO_CONTENT)
async def withdraw_ai_consent(
    user: AuthUser = Depends(current_user), rest: SupabaseRest = Depends(get_rest)
) -> None:
    await rest.update(
        user.token,
        "consents",
        {"user_id": _eq(user.id), "kind": "eq.ai_processing", "withdrawn_at": "is.null"},
        {"withdrawn_at": datetime.now(timezone.utc).isoformat()},
    )


@router.put("/twin")
async def upsert_twin(
    body: TwinIn, character_id: str | None = Query(default=None, max_length=64),
    user: AuthUser = Depends(current_user), rest: SupabaseRest = Depends(get_rest),
) -> dict[str, Any]:
    existing = await target_twin(rest, user, character_id)
    patch = body.model_dump(exclude_none=True)
    if existing is None and character_id:
        raise character_error("character_not_found", "That character doesn't exist.", status.HTTP_404_NOT_FOUND)
    if existing is None:
        if not body.name:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A name is required.")
        try:
            row = await rest.insert(user.token, "twins", {"owner_id": user.id, "kind": "self", **patch})
        except SupabaseError as exc:
            if exc.status_code != 409:
                raise
            existing = await _twin(rest, user)  # lost a race; fall through to update
        else:
            return await _with_portrait_url(rest, user, row)
    assert existing is not None
    if "appearance" in patch:
        patch["appearance"] = {**(existing.get("appearance") or {}), **patch["appearance"]}
    if not patch:
        return await _with_portrait_url(rest, user, existing)
    rows = await rest.update(user.token, "twins", {"owner_id": _eq(user.id), "id": _eq(existing["id"])}, patch)
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Twin not found.")
    return await _with_portrait_url(rest, user, rows[0])


@router.post("/twin/portrait")
async def upload_portrait(
    file: UploadFile = File(...),
    depicts_someone_else: bool = Form(False),
    permission_confirmed: bool = Form(False),
    character_id: str | None = Query(default=None, max_length=64),
    user: AuthUser = Depends(current_user),
    rest: SupabaseRest = Depends(get_rest),
) -> dict[str, Any]:
    twin = await target_twin(rest, user, character_id)
    if twin is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Create your twin's identity first.")
    if depicts_someone_else and not permission_confirmed:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Please confirm you have permission to use this person's portrait.",
        )
    data = await file.read(MAX_PORTRAIT_BYTES + 1)
    if len(data) > MAX_PORTRAIT_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Portrait must be 5 MB or smaller.")
    kind = _sniff(data)  # never trust the client's content-type
    if kind is None:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Use a JPEG, PNG or WebP image.")
    mime, ext = kind
    path = f"{user.id}/portrait-{uuid4().hex}.{ext}"
    await rest.upload_object(user.token, BUCKET, path, data, mime)
    appearance = {**(twin.get("appearance") or {}),
                  "portrait_subject": "other" if depicts_someone_else else "self"}
    try:
        rows = await rest.update(
            user.token, "twins", {"owner_id": _eq(user.id), "id": _eq(twin["id"])},
            {"portrait_path": path, "portrait_permission_confirmed": depicts_someone_else and permission_confirmed,
             "appearance": appearance},
        )
    except SupabaseError:
        await rest.delete_object(user.token, BUCKET, path)  # don't orphan the new file
        raise
    old = twin.get("portrait_path")
    if old and old.startswith(f"{user.id}/"):
        await rest.delete_object(user.token, BUCKET, old)
    return await _with_portrait_url(rest, user, rows[0])


@router.delete("/twin/portrait", status_code=status.HTTP_204_NO_CONTENT)
async def delete_portrait(character_id: str | None = Query(default=None, max_length=64),
                          user: AuthUser = Depends(current_user), rest: SupabaseRest = Depends(get_rest)) -> None:
    twin = await target_twin(rest, user, character_id)
    if twin is None or not twin.get("portrait_path"):
        return
    old = twin["portrait_path"]
    await rest.update(
        user.token, "twins", {"owner_id": _eq(user.id), "id": _eq(twin["id"])},
        {"portrait_path": None, "portrait_permission_confirmed": False},
    )
    if old.startswith(f"{user.id}/"):
        await rest.delete_object(user.token, BUCKET, old)


@router.post("/characters", status_code=status.HTTP_201_CREATED)
async def create_character(body: CharacterCreateIn, user: AuthUser = Depends(current_user),
                           rest: SupabaseRest = Depends(get_rest)) -> dict[str, Any]:
    """Make another, separate character. The personal self-twin is untouched; this one has its own description,
    profile, portrait, conversations and memories."""
    owned = await rest.select(user.token, "twins", {"select": "id", "owner_id": _eq(user.id),
                                                    "limit": str(MAX_CHARACTERS + 1)})
    if len(owned) >= MAX_CHARACTERS:
        raise character_error("character_limit", f"You can have up to {MAX_CHARACTERS} characters.",
                              status.HTTP_422_UNPROCESSABLE_ENTITY)
    desc = body.description.strip()
    row: dict[str, Any] = {"owner_id": user.id, "kind": "character", "name": body.name.strip()}
    if not row["name"]:
        raise character_error("invalid_name", "Give the character a name.", status.HTTP_422_UNPROCESSABLE_ENTITY)
    if body.about is not None:
        row["about"] = body.about.strip()
    ident = {k: v for k, v in (("gender", body.gender), ("pronouns", (body.pronouns or "").strip() or None)) if v}
    if ident:
        row["appearance"] = ident
    if desc:
        row.update({"character_description": desc, "character_version": 1,
                    "character_updated_at": datetime.now(timezone.utc).isoformat()})
    try:
        twin = await rest.insert(user.token, "twins", row)
    except SupabaseError as exc:
        if exc.status_code in (400, 409):
            # The database refused a second twin or a kind='character' row: it has not been upgraded for multiple
            # characters. Say so (actionably) instead of a bare 500, and keep the detail in the server log.
            log.warning("character_insert_rejected status=%s: apply migration 20261015200000_multiple_characters",
                        exc.status_code)
            raise character_error(
                "migration_required", "The database hasn't been upgraded to hold more than one character yet. "
                "Apply the latest migration (20261015200000_multiple_characters) and try again.",
                status.HTTP_503_SERVICE_UNAVAILABLE) from exc
        raise
    return {"twin": await _with_portrait_url(rest, user, twin), "character": character_view(twin, None)}


@router.get("/characters/{character_id}")
async def get_character(character_id: str, user: AuthUser = Depends(current_user),
                        rest: SupabaseRest = Depends(get_rest)) -> dict[str, Any]:
    twin = await owned_character(rest, user, character_id)
    row = await get_profile_row(rest, user, twin["id"])
    return {"twin": await _with_portrait_url(rest, user, twin), "character": character_view(twin, row)}


@router.post("/onboarding/steps/{step}/complete")
async def complete_step(
    step: OnboardingStep, user: AuthUser = Depends(current_user), rest: SupabaseRest = Depends(get_rest)
) -> dict[str, str]:
    """A step is complete only when the server can see the real result, not because a screen was visited."""
    if step in UNAVAILABLE_STEPS:
        raise HTTPException(status.HTTP_409_CONFLICT, UNAVAILABLE_STEPS[step])
    twin = await _twin(rest, user)
    consent = await _active_consent(rest, user) if step == "welcome" else None
    if step == "welcome" and not (consent and consent["version"] == consent_version(get_settings())):
        raise HTTPException(status.HTTP_409_CONFLICT, "Please accept AI processing to continue.")
    if step == "identity" and not (twin and twin.get("name")):
        raise HTTPException(status.HTTP_409_CONFLICT, "Save your twin's identity first.")
    if step == "personality" and not (twin and (twin.get("character_description") or "").strip()):
        raise HTTPException(status.HTTP_409_CONFLICT, "Describe your twin's character first.")
    if step == "refinements" and twin is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Create your twin first.")
    await rest.insert(
        user.token, "onboarding_steps", {"user_id": user.id, "step": step}, upsert_on="user_id,step"
    )
    return {"step": step, "status": "completed"}
