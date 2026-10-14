import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.auth import AuthUser, current_user
from app.questionnaire import QUESTIONS, validate_answers
from app.schemas import ConsentIn, OnboardingStep, PersonalityIn, ProfileIn, TwinIn
from app.supabase_rest import SupabaseError, SupabaseRest, get_rest

router = APIRouter(prefix="/api/v1")

CONSENT_VERSION = "2026-10-v1"
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


async def _twin(rest: SupabaseRest, user: AuthUser) -> dict[str, Any] | None:
    rows = await rest.select(user.token, "twins", {"select": "*", "owner_id": _eq(user.id)})
    return rows[0] if rows else None


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
    return {
        "user_id": user.id,
        "profile": profile[0] if profile else None,
        "twin": await _with_portrait_url(rest, user, twin) if twin else None,
        "completed_steps": sorted(s["step"] for s in steps),
        "ai_consent": {"granted": consent is not None, "version": consent["version"] if consent else None,
                       "current_version": CONSENT_VERSION},
    }


@router.put("/me/profile")
async def update_profile(
    body: ProfileIn, user: AuthUser = Depends(current_user), rest: SupabaseRest = Depends(get_rest)
) -> dict[str, Any]:
    patch = body.model_dump(exclude_none=True)
    if not patch:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Nothing to update.")
    rows = await rest.update(user.token, "profiles", {"id": _eq(user.id)}, patch)
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profile not found.")
    return rows[0]


@router.get("/onboarding/questionnaire")
async def questionnaire(_: AuthUser = Depends(current_user)) -> dict[str, Any]:
    return {"questions": QUESTIONS}


@router.post("/consents/ai-processing", status_code=status.HTTP_201_CREATED)
async def grant_ai_consent(
    body: ConsentIn, user: AuthUser = Depends(current_user), rest: SupabaseRest = Depends(get_rest)
) -> dict[str, Any]:
    if body.version != CONSENT_VERSION:
        raise HTTPException(status.HTTP_409_CONFLICT, "Consent text has changed; please review it again.")
    existing = await _active_consent(rest, user)
    if existing:
        return existing
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
    body: TwinIn, user: AuthUser = Depends(current_user), rest: SupabaseRest = Depends(get_rest)
) -> dict[str, Any]:
    existing = await _twin(rest, user)
    patch = body.model_dump(exclude_none=True)
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
    for key in ("communication", "appearance"):
        if key in patch:
            patch[key] = {**(existing.get(key) or {}), **patch[key]}
    if not patch:
        return await _with_portrait_url(rest, user, existing)
    rows = await rest.update(user.token, "twins", {"owner_id": _eq(user.id), "id": _eq(existing["id"])}, patch)
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Twin not found.")
    return await _with_portrait_url(rest, user, rows[0])


@router.put("/twin/personality")
async def save_personality(
    body: PersonalityIn, user: AuthUser = Depends(current_user), rest: SupabaseRest = Depends(get_rest)
) -> dict[str, Any]:
    twin = await _twin(rest, user)
    if twin is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Create your twin's identity first.")
    try:
        answers = validate_answers(body.answers)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    personality = {"version": 1, "answers": answers, "submitted_at": datetime.now(timezone.utc).isoformat()}
    rows = await rest.update(
        user.token, "twins", {"owner_id": _eq(user.id), "id": _eq(twin["id"])}, {"personality": personality}
    )
    return await _with_portrait_url(rest, user, rows[0])


@router.post("/twin/portrait")
async def upload_portrait(
    file: UploadFile = File(...),
    depicts_someone_else: bool = Form(False),
    permission_confirmed: bool = Form(False),
    user: AuthUser = Depends(current_user),
    rest: SupabaseRest = Depends(get_rest),
) -> dict[str, Any]:
    twin = await _twin(rest, user)
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
async def delete_portrait(user: AuthUser = Depends(current_user), rest: SupabaseRest = Depends(get_rest)) -> None:
    twin = await _twin(rest, user)
    if twin is None or not twin.get("portrait_path"):
        return
    old = twin["portrait_path"]
    await rest.update(
        user.token, "twins", {"owner_id": _eq(user.id), "id": _eq(twin["id"])},
        {"portrait_path": None, "portrait_permission_confirmed": False},
    )
    if old.startswith(f"{user.id}/"):
        await rest.delete_object(user.token, BUCKET, old)


@router.post("/onboarding/steps/{step}/complete")
async def complete_step(
    step: OnboardingStep, user: AuthUser = Depends(current_user), rest: SupabaseRest = Depends(get_rest)
) -> dict[str, str]:
    """A step is complete only when the server can see the real result, not because a screen was visited."""
    if step in UNAVAILABLE_STEPS:
        raise HTTPException(status.HTTP_409_CONFLICT, UNAVAILABLE_STEPS[step])
    twin = await _twin(rest, user)
    if step == "welcome" and await _active_consent(rest, user) is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Please accept AI processing to continue.")
    if step == "identity" and not (twin and twin.get("name")):
        raise HTTPException(status.HTTP_409_CONFLICT, "Save your twin's identity first.")
    if step == "personality" and not (twin and (twin.get("personality") or {}).get("submitted_at")):
        raise HTTPException(status.HTTP_409_CONFLICT, "Save the personality questions first.")
    if step == "refinements" and twin is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Create your twin first.")
    await rest.insert(
        user.token, "onboarding_steps", {"user_id": user.id, "step": step}, upsert_on="user_id,step"
    )
    return {"step": step, "status": "completed"}
