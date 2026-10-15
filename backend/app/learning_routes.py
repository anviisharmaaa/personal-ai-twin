"""Learning preference, memory candidates, approved memories and profile refinements.

Lifecycle:  conversation --(user asks for a review)--> candidates (pending) --(user approves)--> memory (active)
            memory --(optional, user decides)--> profile proposal --(accept/edit)--> profile entry + revision.
Nothing is a memory before approval; the original description is never touched; every accepted profile change keeps a
snapshot of the profile as it was before.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from app.auth import AuthUser, current_user
from app.character import CharacterProfile
from app.character_store import get_profile_row
from app.chat import ChatError, model_gate
from app.config import get_settings
from app.conversation_routes import _UUID, _conversation, _err, _streaming
from app.grounding import ITEM_FIELDS
from app.learning import (
    PROPOSAL_EVIDENCE,
    SECTION_FOR_CATEGORY,
    Extractor,
    OllamaExtractor,
    UnavailableExtractor,
    fingerprint,
    overlap,
    render_conversation,
    validate_candidates,
)
from app.providers import active_provider, consent_version, ollama_endpoint_ok
from app.routes import _active_consent, _eq, _twin
from app.supabase_rest import SupabaseError, SupabaseRest, get_rest

router = APIRouter(prefix="/api/v1")
log = logging.getLogger("madhuora.learning")

DISCLOSURE_VERSION = "2026-10-learning-v1"
CONFLICT_OVERLAP = 0.5
# Conversations whose review is running in THIS process. After a restart the set is empty, so nothing stays "running".
_reviewing: set[str] = set()


def get_extractor() -> Extractor | UnavailableExtractor:
    s = get_settings()
    p = active_provider(s)
    if p == "ollama":
        if not s.ollama_character_model:
            return UnavailableExtractor("not_configured", "No local model is set.")
        if not ollama_endpoint_ok(s):
            return UnavailableExtractor("local_unavailable", "The local model address isn't allowed.")
        return OllamaExtractor(s.ollama_base_url, s.ollama_character_model, s.learning_timeout_seconds,
                               s.learning_max_output_tokens)
    if p == "mock":
        return UnavailableExtractor("learning_unavailable_in_sample_mode",
                                    "Sample mode can't learn: no real model reads your conversations.")
    if p in ("nvidia", "openai"):
        return UnavailableExtractor("learning_provider_unsupported",
                                    "Learning from conversations is only available with the local model.")
    return UnavailableExtractor("ai_off", "No AI provider is selected.")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _public(row: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {k: row.get(k) for k in keys}


CAND_KEYS = ("id", "statement", "category", "scope", "evidence_type", "supporting", "status", "conversation_id",
             "created_at")
MEM_KEYS = ("id", "statement", "category", "scope", "evidence_type", "supporting", "source_deleted", "edited",
            "pinned", "status", "superseded_by", "conversation_id", "created_at", "updated_at")
PROP_KEYS = ("id", "memory_id", "section", "current_text", "proposed_text", "kind", "evidence", "status",
             "created_at", "resolved_at")


async def _own_twin(rest: SupabaseRest, user: AuthUser) -> dict[str, Any]:
    twin = await _twin(rest, user)
    if twin is None:
        raise _err("no_twin", "Create your twin's identity first.", status.HTTP_409_CONFLICT)
    return twin


async def _one(rest: SupabaseRest, user: AuthUser, table: str, rid: str) -> dict[str, Any]:
    rows = await rest.select(user.token, table, {"select": "*", "id": _eq(rid), "owner_id": _eq(user.id)}) \
        if _UUID.match(rid) else []
    if not rows:
        raise _err("not_found", "That item doesn't exist.", status.HTTP_404_NOT_FOUND)
    return rows[0]


# ---- preference ------------------------------------------------------------------------------------------------------

class PreferenceIn(BaseModel):
    enabled: bool
    disclosure_version: str | None = Field(default=None, max_length=64)


async def _preference(rest: SupabaseRest, user: AuthUser) -> dict[str, Any] | None:
    rows = await rest.select(user.token, "learning_preferences", {"select": "*", "owner_id": _eq(user.id)})
    return rows[0] if rows else None


def _pref_view(row: dict[str, Any] | None) -> dict[str, Any]:
    return {"enabled": bool(row and row.get("enabled")), "enabled_at": row.get("enabled_at") if row else None,
            "disabled_at": row.get("disabled_at") if row else None,
            "accepted_disclosure_version": row.get("disclosure_version") if row else None,
            "current_disclosure_version": DISCLOSURE_VERSION}


@router.get("/learning/preference")
async def get_preference(user: AuthUser = Depends(current_user), rest: SupabaseRest = Depends(get_rest)
                         ) -> dict[str, Any]:
    return _pref_view(await _preference(rest, user))


@router.put("/learning/preference")
async def set_preference(body: PreferenceIn, user: AuthUser = Depends(current_user),
                         rest: SupabaseRest = Depends(get_rest)) -> dict[str, Any]:
    """Separate from the AI-processing consent. Turning it OFF stops new reviews; it deletes nothing."""
    if body.enabled and body.disclosure_version != DISCLOSURE_VERSION:
        raise _err("disclosure_required", "Please read and accept the current learning explanation first.",
                   status.HTTP_422_UNPROCESSABLE_ENTITY)
    now = _now()
    row = await _preference(rest, user)
    fields: dict[str, Any] = {"enabled": body.enabled, "updated_at": now}
    if body.enabled:
        fields.update(enabled_at=now, disclosure_version=DISCLOSURE_VERSION)
    else:
        fields["disabled_at"] = now
    if row is None:
        row = await rest.insert(user.token, "learning_preferences", {"owner_id": user.id, **fields})
    else:
        row = (await rest.update(user.token, "learning_preferences", {"owner_id": _eq(user.id)}, fields))[0]
    return _pref_view(row)


# ---- review (extraction) ---------------------------------------------------------------------------------------------

async def _learning_ready(rest: SupabaseRest, user: AuthUser) -> None:
    """The conditions that must hold when a review is requested AND again just before it writes anything."""
    s = get_settings()
    pref = await _preference(rest, user)
    if not (pref and pref.get("enabled")):
        raise _err("learning_disabled", "Learning from conversations is switched off.", status.HTTP_403_FORBIDDEN)
    consent = await _active_consent(rest, user)
    if consent is None or consent.get("version") != consent_version(s):
        raise _err("consent_required", "Please accept AI processing in Settings first.", status.HTTP_403_FORBIDDEN)


@router.post("/conversations/{cid}/learning/review", status_code=status.HTTP_202_ACCEPTED)
async def start_review(cid: str, background: BackgroundTasks, user: AuthUser = Depends(current_user),
                       rest: SupabaseRest = Depends(get_rest),
                       extractor: Extractor | UnavailableExtractor = Depends(get_extractor)) -> JSONResponse:
    s = get_settings()
    conv = await _conversation(rest, user, cid)
    twin = await _own_twin(rest, user)
    await _learning_ready(rest, user)
    if not s.ai_enabled:
        raise _err("ai_disabled", "AI is temporarily switched off.", status.HTTP_503_SERVICE_UNAVAILABLE)
    if isinstance(extractor, UnavailableExtractor):
        raise _err(extractor.code, extractor.message, status.HTTP_503_SERVICE_UNAVAILABLE)
    messages = await _review_messages(rest, user, cid, s.learning_review_messages)
    if not any(m["role"] == "user" for m in messages):
        raise _err("nothing_to_review", "There is nothing in this conversation to review yet.",
                   status.HTTP_409_CONFLICT)
    if cid in _reviewing:
        raise _err("in_progress", "This conversation is already being reviewed.", status.HTTP_409_CONFLICT)
    if cid in _streaming:
        raise _err("in_progress", "A reply is being written. Review after it finishes.", status.HTTP_409_CONFLICT)
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    recent = await rest.select(user.token, "conversations", {
        "select": "id", "owner_id": _eq(user.id), "learning_reviewed_at": f"gte.{since}",
        "limit": str(s.learning_reviews_per_hour + 1)})
    if len(recent) >= s.learning_reviews_per_hour:
        raise _err("rate_limited", "You've run several reviews this hour. Please try again later.",
                   status.HTTP_429_TOO_MANY_REQUESTS)
    if not model_gate.try_acquire():
        raise _err("model_busy", "The local model is busy with another job. Try again in a moment.",
                   status.HTTP_429_TOO_MANY_REQUESTS)
    _reviewing.add(cid)
    background.add_task(_run_review, rest, user, twin, conv, extractor)
    return JSONResponse({"state": "running", "conversation_id": cid}, status_code=status.HTTP_202_ACCEPTED)


async def _review_messages(rest: SupabaseRest, user: AuthUser, cid: str, limit: int) -> list[dict[str, Any]]:
    rows = await rest.select(user.token, "messages", {
        "select": "*", "conversation_id": _eq(cid), "owner_id": _eq(user.id), "status": "eq.complete",
        "order": "created_at.desc", "limit": str(limit)})
    return list(reversed(rows))


async def _set_outcome(rest: SupabaseRest, user: AuthUser, cid: str, failure: str | None) -> None:
    try:
        await rest.update(user.token, "conversations", {"id": _eq(cid), "owner_id": _eq(user.id)},
                          {"learning_reviewed_at": _now(), "learning_failure_code": failure})
    except SupabaseError:
        log.warning("learning_outcome_not_saved")


async def _run_review(rest: SupabaseRest, user: AuthUser, twin: dict[str, Any], conv: dict[str, Any],
                      extractor: Extractor) -> None:
    """Background job. A failure here is recorded as a code on the conversation and never touches the chat itself."""
    cid = conv["id"]
    s = get_settings()
    try:
        messages = await _review_messages(rest, user, cid, s.learning_review_messages)
        text, user_msgs = render_conversation(messages)
        known = {c["fingerprint"] for c in await rest.select(user.token, "memory_candidates", {
            "select": "fingerprint", "owner_id": _eq(user.id), "twin_id": _eq(twin["id"]), "limit": "2000"})}
        known |= {m["fingerprint"] for m in await rest.select(user.token, "memories", {
            "select": "fingerprint", "owner_id": _eq(user.id), "twin_id": _eq(twin["id"]), "limit": "2000"})}
        try:
            raw = await extractor.extract(text)
        except ChatError as e:
            log.warning("learning_failed code=%s detail=%s", e.code, e.detail or "-")
            await _set_outcome(rest, user, cid, e.code)
            return
        accepted, rej = validate_candidates(raw, user_msgs, known, s.learning_max_candidates)
        # The user may have withdrawn consent or switched learning off while the model was thinking.
        try:
            await _learning_ready(rest, user)
        except Exception:  # noqa: BLE001 - HTTPException from the shared check
            log.info("learning_cancelled reason=consent_or_preference_changed")
            return
        for c in accepted:
            await rest.insert(user.token, "memory_candidates", {
                "owner_id": user.id, "twin_id": twin["id"], "conversation_id": cid, "status": "pending", **c})
        log.info("learning_done candidates=%d rejected=%s", len(accepted), dict(rej.counts))
        await _set_outcome(rest, user, cid, None)
    except SupabaseError:
        log.warning("learning_persist_failed")
        await _set_outcome(rest, user, cid, "persist_failed")
    except Exception as exc:  # noqa: BLE001 - never die silently with the page waiting
        log.error("learning_crashed type=%s", type(exc).__name__)
        await _set_outcome(rest, user, cid, "internal_error")
    finally:
        _reviewing.discard(cid)
        model_gate.release()


@router.get("/conversations/{cid}/learning")
async def review_status(cid: str, user: AuthUser = Depends(current_user), rest: SupabaseRest = Depends(get_rest)
                        ) -> dict[str, Any]:
    conv = await _conversation(rest, user, cid)
    pending = await rest.select(user.token, "memory_candidates", {
        "select": "*", "owner_id": _eq(user.id), "conversation_id": _eq(cid), "status": "eq.pending",
        "order": "created_at.asc", "limit": "50"})
    return {"state": "running" if cid in _reviewing else "idle", "reviewed_at": conv.get("learning_reviewed_at"),
            "failure_code": conv.get("learning_failure_code"),
            "candidates": [_public(c, CAND_KEYS) for c in pending]}


# ---- candidates ----------------------------------------------------------------------------------------------------

@router.get("/memory/candidates")
async def list_candidates(user: AuthUser = Depends(current_user), rest: SupabaseRest = Depends(get_rest)
                          ) -> dict[str, Any]:
    rows = await rest.select(user.token, "memory_candidates", {
        "select": "*", "owner_id": _eq(user.id), "status": "eq.pending", "order": "created_at.desc", "limit": "100"})
    return {"candidates": [_public(c, CAND_KEYS) for c in rows]}


class ApproveIn(BaseModel):
    statement: str | None = Field(default=None, min_length=1, max_length=240)
    resolution: Literal["keep_both", "replace"] | None = None


@router.post("/memory/candidates/{rid}/approve", status_code=status.HTTP_201_CREATED)
async def approve_candidate(rid: str, body: ApproveIn, user: AuthUser = Depends(current_user),
                            rest: SupabaseRest = Depends(get_rest)) -> dict[str, Any]:
    cand = await _one(rest, user, "memory_candidates", rid)
    if cand["status"] != "pending":
        raise _err("not_pending", "That suggestion was already handled.", status.HTTP_409_CONFLICT)
    text = (body.statement or cand["statement"]).strip()
    edited = text != cand["statement"]
    fp = fingerprint(text)
    active = await rest.select(user.token, "memories", {
        "select": "*", "owner_id": _eq(user.id), "twin_id": _eq(cand["twin_id"]), "status": "eq.active",
        "limit": "500"})
    if any(m["fingerprint"] == fp for m in active):
        raise _err("duplicate", "Madhuora already remembers this.", status.HTTP_409_CONFLICT)
    clash = [m for m in active if overlap(text, m["statement"]) >= CONFLICT_OVERLAP]
    if clash and body.resolution is None:
        # Never choose silently: the user says whether this replaces the older memory or sits beside it.
        raise _conflict(clash)
    memory = await rest.insert(user.token, "memories", {
        "owner_id": user.id, "twin_id": cand["twin_id"], "candidate_id": cand["id"],
        "conversation_id": cand.get("conversation_id"), "statement": text, "category": cand["category"],
        "scope": cand.get("scope", ""), "evidence_type": cand["evidence_type"], "supporting": cand["supporting"],
        "edited": edited, "fingerprint": fp})
    if clash and body.resolution == "replace":
        for old in clash:
            await rest.update(user.token, "memories", {"id": _eq(old["id"]), "owner_id": _eq(user.id)},
                              {"status": "superseded", "superseded_by": memory["id"], "updated_at": _now()})
    await rest.update(user.token, "memory_candidates", {"id": _eq(cand["id"]), "owner_id": _eq(user.id)},
                      {"status": "approved", "reviewed_at": _now()})
    proposal = await _maybe_propose(rest, user, memory)
    return {"memory": _public(memory, MEM_KEYS), "profile_proposal": proposal}


def _conflict(clash: list[dict[str, Any]]) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, {
        "code": "conflict", "message": "This overlaps with something Madhuora already remembers. Choose what to do.",
        "conflicting": [{"id": m["id"], "statement": m["statement"]} for m in clash]})


class RejectIn(BaseModel):
    reason: Literal["wrong", "not_relevant", "private"] = "wrong"


async def _tombstone_candidate(rest: SupabaseRest, user: AuthUser, cand_id: str, reason: str) -> None:
    """Keep only the fingerprint, so the idea is not suggested again, and drop the text and the quotes."""
    await rest.update(user.token, "memory_candidates", {"id": _eq(cand_id), "owner_id": _eq(user.id)},
                      {"status": "rejected", "statement": "", "supporting": [], "rejected_reason": reason,
                       "reviewed_at": _now()})


@router.post("/memory/candidates/{rid}/reject")
async def reject_candidate(rid: str, body: RejectIn, user: AuthUser = Depends(current_user),
                           rest: SupabaseRest = Depends(get_rest)) -> dict[str, Any]:
    cand = await _one(rest, user, "memory_candidates", rid)
    if cand["status"] != "pending":
        raise _err("not_pending", "That suggestion was already handled.", status.HTTP_409_CONFLICT)
    await _tombstone_candidate(rest, user, cand["id"], body.reason)
    return {"id": cand["id"], "status": "rejected"}


# ---- memories ------------------------------------------------------------------------------------------------------

@router.get("/memories")
async def list_memories(include_superseded: bool = Query(default=False), user: AuthUser = Depends(current_user),
                        rest: SupabaseRest = Depends(get_rest)) -> dict[str, Any]:
    params = {"select": "*", "owner_id": _eq(user.id), "order": "created_at.desc", "limit": "300"}
    if not include_superseded:
        params["status"] = "eq.active"
    rows = await rest.select(user.token, "memories", params)
    return {"memories": [_public(m, MEM_KEYS) for m in rows]}


class MemoryPatch(BaseModel):
    statement: str | None = Field(default=None, min_length=1, max_length=240)
    scope: str | None = Field(default=None, max_length=160)
    pinned: bool | None = None


@router.patch("/memories/{rid}")
async def patch_memory(rid: str, body: MemoryPatch, user: AuthUser = Depends(current_user),
                       rest: SupabaseRest = Depends(get_rest)) -> dict[str, Any]:
    mem = await _one(rest, user, "memories", rid)
    if mem["status"] != "active":
        raise _err("superseded", "That memory was replaced by a newer one.", status.HTTP_409_CONFLICT)
    fields: dict[str, Any] = {"updated_at": _now()}
    if body.statement is not None and body.statement.strip() != mem["statement"]:
        text = body.statement.strip()
        fp = fingerprint(text)
        others = await rest.select(user.token, "memories", {
            "select": "id,fingerprint", "owner_id": _eq(user.id), "twin_id": _eq(mem["twin_id"]),
            "status": "eq.active", "limit": "500"})
        if any(o["fingerprint"] == fp and o["id"] != mem["id"] for o in others):
            raise _err("duplicate", "Madhuora already remembers this.", status.HTTP_409_CONFLICT)
        fields.update(statement=text, fingerprint=fp, edited=True)
    if body.scope is not None:
        fields["scope"] = body.scope.strip()
    if body.pinned is not None:
        fields["pinned"] = body.pinned
    rows = await rest.update(user.token, "memories", {"id": _eq(mem["id"]), "owner_id": _eq(user.id)}, fields)
    return {"memory": _public(rows[0], MEM_KEYS)}


@router.delete("/memories/{rid}", status_code=status.HTTP_204_NO_CONTENT)
async def forget_memory(rid: str, incorrect: bool = Query(default=False), user: AuthUser = Depends(current_user),
                        rest: SupabaseRest = Depends(get_rest)) -> None:
    """Forget a memory. Its text is removed; only its fingerprint stays (as a rejected idea) so it isn't suggested
    again. Already-accepted profile changes stay (their snapshots are in the history); pending proposals go."""
    mem = await _one(rest, user, "memories", rid)
    await rest.delete(user.token, "profile_proposals",
                      {"memory_id": _eq(mem["id"]), "owner_id": _eq(user.id), "status": "in.(pending,deferred)"})
    reason = "incorrect" if incorrect else "forgotten"
    if mem.get("candidate_id"):
        await _tombstone_candidate(rest, user, mem["candidate_id"], reason)
    else:
        await rest.insert(user.token, "memory_candidates", {
            "owner_id": user.id, "twin_id": mem["twin_id"], "statement": "", "category": mem["category"],
            "scope": "", "evidence_type": mem["evidence_type"], "supporting": [], "status": "rejected",
            "fingerprint": mem["fingerprint"], "rejected_reason": reason})
    await rest.delete(user.token, "memories", {"id": _eq(mem["id"]), "owner_id": _eq(user.id)})


# ---- profile refinements -------------------------------------------------------------------------------------------

KIND_FOR = {"correction": "correction", "repeated_pattern": "new_evidence"}
BASIS_FOR = {"correction": "stated", "repeated_pattern": "inferred"}
SECTIONS = tuple(ITEM_FIELDS)


async def _maybe_propose(rest: SupabaseRest, user: AuthUser, memory: dict[str, Any],
                         section: str | None = None) -> dict[str, Any] | None:
    if section is None:
        if memory["evidence_type"] not in PROPOSAL_EVIDENCE or memory["category"] not in SECTION_FOR_CATEGORY:
            return None
        section = SECTION_FOR_CATEGORY[memory["category"]]
    row = await get_profile_row(rest, user, memory["twin_id"])
    if not row or row.get("profile") is None:
        return None
    open_ = await rest.select(user.token, "profile_proposals", {
        "select": "*", "owner_id": _eq(user.id), "memory_id": _eq(memory["id"]), "status": "in.(pending,deferred)"})
    if open_:
        return _public(open_[0], PROP_KEYS)
    kind = "contextual_exception" if memory["category"] == "context_behaviour" else \
        KIND_FOR.get(memory["evidence_type"], "new_evidence")
    created = await rest.insert(user.token, "profile_proposals", {
        "owner_id": user.id, "twin_id": memory["twin_id"], "memory_id": memory["id"], "section": section,
        "current_text": "", "proposed_text": memory["statement"][:320], "kind": kind,
        "evidence": [s.get("quote", "") for s in (memory.get("supporting") or [])][:3], "status": "pending"})
    return _public(created, PROP_KEYS)


class ProposeIn(BaseModel):
    section: Literal[
        "core_traits", "speaking_style", "warmth_and_expressiveness", "humour_and_playfulness",
        "empathy_and_support", "directness_and_disagreement", "values_and_motivations", "relationships_and_social",
        "interests_and_habits", "communication_preferences", "boundaries_and_careful_topics", "response_patterns"]


@router.post("/memories/{rid}/profile-proposal", status_code=status.HTTP_201_CREATED)
async def propose_from_memory(rid: str, body: ProposeIn, user: AuthUser = Depends(current_user),
                              rest: SupabaseRest = Depends(get_rest)) -> dict[str, Any]:
    mem = await _one(rest, user, "memories", rid)
    if mem["status"] != "active":
        raise _err("superseded", "That memory was replaced by a newer one.", status.HTTP_409_CONFLICT)
    proposal = await _maybe_propose(rest, user, mem, body.section)
    if proposal is None:
        raise _err("no_profile", "Understand the character first: there is no profile to refine yet.",
                   status.HTTP_409_CONFLICT)
    return {"profile_proposal": proposal}


@router.get("/profile-proposals")
async def list_proposals(user: AuthUser = Depends(current_user), rest: SupabaseRest = Depends(get_rest)
                         ) -> dict[str, Any]:
    rows = await rest.select(user.token, "profile_proposals", {
        "select": "*", "owner_id": _eq(user.id), "status": "in.(pending,deferred)", "order": "created_at.desc",
        "limit": "100"})
    return {"proposals": [_public(p, PROP_KEYS) for p in rows]}


class ResolveIn(BaseModel):
    action: Literal["accept", "reject", "defer"]
    text: str | None = Field(default=None, min_length=1, max_length=320)


@router.post("/profile-proposals/{rid}/resolve")
async def resolve_proposal(rid: str, body: ResolveIn, user: AuthUser = Depends(current_user),
                           rest: SupabaseRest = Depends(get_rest)) -> dict[str, Any]:
    prop = await _one(rest, user, "profile_proposals", rid)
    if prop["status"] not in ("pending", "deferred"):
        raise _err("not_pending", "That suggestion was already handled.", status.HTTP_409_CONFLICT)
    key = {"id": _eq(prop["id"]), "owner_id": _eq(user.id)}
    if body.action in ("reject", "defer"):
        await rest.update(user.token, "profile_proposals", key, {
            "status": "rejected" if body.action == "reject" else "deferred",
            "resolved_at": _now() if body.action == "reject" else None})
        return {"id": prop["id"], "status": "rejected" if body.action == "reject" else "deferred"}

    row = await get_profile_row(rest, user, prop["twin_id"])
    if not row or row.get("profile") is None:
        raise _err("no_profile", "There is no profile to change.", status.HTTP_409_CONFLICT)
    profile = dict(row["profile"])
    memory = None
    if prop.get("memory_id"):
        found = await rest.select(user.token, "memories", {"select": "*", "id": _eq(prop["memory_id"]),
                                                           "owner_id": _eq(user.id)})
        memory = found[0] if found else None
    if memory is None:
        raise _err("source_gone", "The memory behind this suggestion was forgotten.", status.HTTP_409_CONFLICT)
    basis = "context_dependent" if memory["category"] == "context_behaviour" else \
        BASIS_FOR.get(memory["evidence_type"], "inferred")
    text = (body.text or prop["proposed_text"]).strip()
    changed = dict(profile)
    changed[prop["section"]] = [*profile.get(prop["section"], []), {"text": text, "basis": basis}]
    try:
        CharacterProfile.model_validate(changed)
    except ValidationError as e:
        raise _err("section_full", "That section is full. Edit the profile directly or defer this suggestion.",
                   status.HTTP_409_CONFLICT) from e
    # Snapshot first: if a later step fails, the history still holds the profile as it was.
    await rest.insert(user.token, "profile_revisions", {
        "owner_id": user.id, "twin_id": prop["twin_id"], "profile": profile, "reason": "proposal_accepted",
        "proposal_id": prop["id"]})
    await rest.update(user.token, "character_profiles", {"owner_id": _eq(user.id), "twin_id": _eq(prop["twin_id"])},
                      {"profile": changed, "updated_at": _now()})
    await rest.update(user.token, "profile_proposals", key, {"status": "accepted", "resolved_at": _now(),
                                                             "proposed_text": text})
    return {"id": prop["id"], "status": "accepted", "section": prop["section"], "added": {"text": text, "basis": basis}}


@router.get("/profile-revisions")
async def list_revisions(user: AuthUser = Depends(current_user), rest: SupabaseRest = Depends(get_rest)
                         ) -> dict[str, Any]:
    rows = await rest.select(user.token, "profile_revisions", {
        "select": "*", "owner_id": _eq(user.id), "order": "created_at.desc", "limit": "20"})
    return {"revisions": [_public(r, ("id", "profile", "reason", "proposal_id", "created_at")) for r in rows]}

