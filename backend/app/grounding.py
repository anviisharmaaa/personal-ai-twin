"""Objective checks on a model's character profile, run BEFORE anything is saved.

Rules of this module:
- It only REMOVES things that are objectively unsupported (a quote that is not in the description, a duplicate,
  entries over a sparse-input budget). It never writes, rewrites or "repairs" text.
- If what is left would be mostly ungrounded, or a sensitive attribute was introduced that the description does
  not support, the whole profile is REJECTED (AnalysisError "quality_failed"); the caller keeps the last good one.
- It never logs or returns content, only counts.
"""

import logging
import re
from dataclasses import dataclass, field

from app.character import AnalysisError, CharacterProfile

log = logging.getLogger("madhuora.grounding")

# A description with fewer words than this is "sparse": the profile may hold at most SPARSE_MAX_ENTRIES entries.
SPARSE_WORDS = 20
SPARSE_MAX_ENTRIES = 6
SPARSE_MAX_UNCERTAINTIES = 3
SPARSE_MAX_GUIDANCE = 1

ITEM_FIELDS = (
    "core_traits", "speaking_style", "warmth_and_expressiveness", "humour_and_playfulness", "empathy_and_support",
    "directness_and_disagreement", "values_and_motivations", "relationships_and_social", "interests_and_habits",
    "communication_preferences", "boundaries_and_careful_topics", "response_patterns",
)
STRING_FIELDS = ("typical_expressions", "behavioural_guidance", "uncertainties")


def _norm(s: str) -> str:
    """Case, quote-style and whitespace insensitive form used ONLY to compare a quote against the description."""
    s = s.translate({0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"', 0x2013: "-", 0x2014: "-"})
    return re.sub(r"\s+", " ", s).strip().casefold()


def _core(s: str) -> str:
    """Quote with surrounding quotes/punctuation removed, so "'Chal, theek hai'." still matches."""
    return _norm(s).strip(" \t\n.,;:!?'\"()[]")


def is_verbatim(quote: str, description: str) -> bool:
    """True only for a non-empty, contiguous span of the description (ellipses and stitched fragments fail)."""
    q = _core(quote)
    return bool(q) and "..." not in q and "…" not in q and q in _norm(description)


def is_sparse(description: str) -> bool:
    return len(description.split()) < SPARSE_WORDS


def entry_count(profile: CharacterProfile) -> int:
    """Deterministic size of a profile: the number of entries across EVERY list field (traits, tendencies,
    expressions, guidance and uncertainties alike). The summary is not counted."""
    return sum(len(getattr(profile, f)) for f in (*ITEM_FIELDS, *STRING_FIELDS, "context_tendencies"))


# --- sensitive attributes -------------------------------------------------------------------------------------
# Tier A: a specific identity or label. It may appear in the profile only if the description names it literally.
# (Practices alone, e.g. "prays five times a day", never license naming a religion.)
_IDENTITIES = re.compile(
    r"\b(muslims?|islam\w*|hindus?|hinduism|christians?|christianity|sikhs?|sikhism|jews?|jewish|buddhists?|buddhism|"
    r"atheists?|atheism|agnostics?|gay|lesbians?|bisexual\w*|transgender|homosexual\w*|heterosexual\w*)\b", re.I)
# Tier B: a topic family. The profile may touch it only if the description touches the same family.
_FAMILIES: dict[str, re.Pattern[str]] = {
    "religion": re.compile(
        r"\b(religio\w*|faith\w*|spiritual\w*|devout\w*|pray\w*|worship\w*|scripture\w*|god)\b", re.I),
    "politics": re.compile(r"\b(politic\w*|partisan\w*)\b", re.I),
    "health": re.compile(
        r"\b(diagnos\w*|depress\w*|anxiety|anxious|disorder\w*|bipolar|adhd|autis\w*|ptsd|trauma\w*|narcissis\w*|"
        r"mental health|mentally ill|illness\w*|psychiatr\w*|therapy|medicat\w*)\b", re.I),
}


def sensitive_violations(output_text: str, description: str) -> list[str]:
    """Names of sensitive categories the output introduces that the description does not support."""
    out: list[str] = []
    named = {m.group(0).casefold() for m in _IDENTITIES.finditer(description)}
    if {m.group(0).casefold() for m in _IDENTITIES.finditer(output_text)} - named:
        out.append("identity_label")
    for family, pat in _FAMILIES.items():
        if pat.search(output_text) and not pat.search(description):
            out.append(family)
    return out


# --- the validator --------------------------------------------------------------------------------------------

@dataclass
class Adjustments:
    """Counts only. Non-zero values mean the MODEL's raw output needed fixing (a prompt-quality signal)."""

    expressions_dropped: int = 0
    tendencies_dropped: int = 0
    duplicates_dropped: int = 0
    sparse_trimmed: int = 0
    raw_entries: int = 0
    raw_tendencies: int = 0
    sparse: bool = False
    extra: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, int]:
        return {k: int(v) for k, v in self.__dict__.items() if k != "extra"}


def _reject(reason: str) -> AnalysisError:
    log.warning("quality_rejected reason=%s", reason)  # reason is a fixed code, never content
    return AnalysisError(
        "quality_failed",
        "The AI's interpretation didn't pass our checks against your description, so it wasn't saved. "
        "Your previous interpretation is unchanged. Please try again.",
        502, f"reason={reason}",
    )


def ground(profile: CharacterProfile, description: str, *, require_evidence: bool = True
           ) -> tuple[CharacterProfile, Adjustments]:
    """Return a profile containing only what can be checked against `description`, or raise quality_failed."""
    adj = Adjustments(raw_entries=entry_count(profile), raw_tendencies=len(profile.context_tendencies),
                      sparse=is_sparse(description))
    data = profile.model_dump()

    # 1. Typical expressions must be exact, contiguous text from the description.
    kept = [q for q in data["typical_expressions"] if is_verbatim(q, description)]
    adj.expressions_dropped = len(data["typical_expressions"]) - len(kept)
    data["typical_expressions"] = kept

    # 2. Every contextual tendency must carry a verbatim quote that supports it.
    if require_evidence:
        ctx = [c for c in data["context_tendencies"] if is_verbatim(c.get("evidence", ""), description)]
        adj.tendencies_dropped = len(data["context_tendencies"]) - len(ctx)
        if adj.raw_tendencies and adj.tendencies_dropped * 2 > adj.raw_tendencies:
            raise _reject("ungrounded_context")  # most of it cites nothing real: do not save a patched remainder
        data["context_tendencies"] = ctx

    # 3. Exact duplicates (same text in two places) are removed; the first occurrence stays.
    seen: set[str] = set()

    def fresh(text: str) -> bool:
        key = _core(text)
        if key in seen:
            return False
        seen.add(key)
        return True

    for f in ITEM_FIELDS:
        before = len(data[f])
        data[f] = [i for i in data[f] if fresh(i["text"])]
        adj.duplicates_dropped += before - len(data[f])
    for f in ("behavioural_guidance", "uncertainties"):
        before = len(data[f])
        data[f] = [s for s in data[f] if fresh(s)]
        adj.duplicates_dropped += before - len(data[f])

    # 4. Sparse input: bounded size. Extra uncertainties/guidance are removed; anything still over budget means the
    #    model invented facts, which cannot be fixed by removal.
    if adj.sparse:
        for f, cap in (("uncertainties", SPARSE_MAX_UNCERTAINTIES), ("behavioural_guidance", SPARSE_MAX_GUIDANCE)):
            adj.sparse_trimmed += max(0, len(data[f]) - cap)
            data[f] = data[f][:cap]

    result = CharacterProfile.model_validate(data)
    if adj.sparse and entry_count(result) > SPARSE_MAX_ENTRIES:
        raise _reject("sparse_overfilled")

    # 5. Unsupported sensitive attributes. The summary is part of the output and is checked too.
    if sensitive_violations(result.model_dump_json(), description):
        raise _reject("unsupported_sensitive")

    log.info("grounded raw_entries=%d kept_entries=%d expr_dropped=%d ctx_dropped=%d dup_dropped=%d trimmed=%d",
             adj.raw_entries, entry_count(result), adj.expressions_dropped, adj.tendencies_dropped,
             adj.duplicates_dropped, adj.sparse_trimmed)
    return result, adj

