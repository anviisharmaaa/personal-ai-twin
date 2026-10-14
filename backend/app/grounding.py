"""Objective checks on a model's character profile, run BEFORE anything is saved.

Rules of this module:
- It only REMOVES things that are objectively unsupported (a quote that is not in the description, a duplicate,
  entries over a sparse-input budget). It never writes, rewrites or "repairs" text.
- If what is left would be mostly ungrounded, or a sensitive attribute was introduced that the description does
  not support, the whole profile is REJECTED (AnalysisError "quality_failed"); the caller keeps the last good one.
- It never logs content, only counts. `Adjustments.removed` keeps what was removed IN MEMORY ONLY, for the
  operator's evaluation script; it is never logged, never stored and never part of `as_dict()`.
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



# --- duplicate detection --------------------------------------------------------------------------------------
# Two entries are treated as the same observation only when ONE of them says nothing the other does not already
# say: its content words (after light normalisation) are all contained in the other's. Entries that merely share
# wording, but each add a word (another person, setting, number, or an opposite attitude), both stay. The saved
# description and the surviving entries are never edited; this only decides which entry to remove.
_STOP = frozenset((
    "a an the and or but of to in on at by for with from into onto over under around about as is are was were be been "
    "being am it its this that these those she he her his hers him they them their theirs we us our you your i me my "
    "herself himself themselves who whom which when while then than so very quite also just too does do did has have "
    "had will would can could may might shall should often usually generally tends tend always go goes goe").split())
# Words that change what a sentence MEANS. They are kept as tokens and must match between two entries.
_NEGATIONS = frozenset(("not", "no", "never", "without", "cannot", "nor", "n't", "neither", "hardly", "rarely"))
_POSITIVE = frozenset(("love", "like", "enjoy", "adore", "relish"))
_NEGATIVE = frozenset(("hate", "dislike", "detest", "resent", "loathe"))
_CONTRAST = frozenset(("instead", "rather"))   # "instead of" / "rather than" are the same contrast
_NUMBERS = frozenset(("one two three four five six seven eight nine ten once twice thrice half double "
                      "first second third").split())
_WORD = re.compile(r"[\w']+", re.UNICODE)


def _stem(w: str) -> str:
    for suffix, repl in (("ily", "y"), ("ing", ""), ("edly", ""), ("ed", ""), ("es", ""), ("s", "")):
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            w = w[: -len(suffix)] + repl
            break
    return w[:-1] if len(w) > 3 and w.endswith("e") else w


_POS_STEMS = frozenset(_stem(w) for w in _POSITIVE)   # loves/loved/loving/love -> the same stem
_NEG_STEMS = frozenset(_stem(w) for w in _NEGATIVE)


def _tokens(text: str) -> frozenset[str]:
    """Content words of an entry; the polarity of love/hate-type verbs and negations are kept as markers."""
    out: set[str] = set()
    for raw in _WORD.findall(_norm(text).replace("n't", " not")):
        w = raw.strip("'")
        if not w or w in _STOP:
            continue
        if w in _NEGATIONS:
            out.add("¬")
            continue
        if w in _CONTRAST:
            out.add("instead")
            continue
        s = _stem(w)
        if s in _POS_STEMS:
            out.add("+")
        elif s in _NEG_STEMS:
            out.add("-")
        else:
            out.add(w if w in _NUMBERS or any(c.isdigit() for c in w) else s)
    return frozenset(out)


def _covers(big: frozenset[str], small: frozenset[str]) -> bool:
    """True if `big` already says everything `small` says (and small has enough words to be a real claim)."""
    if len(small) < 2 or not small <= big:
        return False
    # An entry that adds a negation or an opposite attitude says something different, not more ("Loves noise" is not
    # covered by "Hates noise, loves music"). Extra detail such as a number or another word only adds to the claim; a
    # DIFFERENT number is already a mismatch, because then `small` is not contained in `big`.
    markers = (big - small) & {"¬", "+", "-"}
    # A negation in `big` that `small` lacks reverses the claim. An extra like/dislike only matters when `small`
    # itself states an attitude (then `big` may say the opposite); an entry with no attitude ("Gets short with people
    # who interrupt her") is still fully contained in "Hates being rushed and gets short with people who interrupt her".
    return not ("¬" in markers or (markers and small & {"+", "-"}))

# --- the validator --------------------------------------------------------------------------------------------

@dataclass
class Adjustments:
    """Counts only. Non-zero values mean the MODEL's raw output needed fixing (a prompt-quality signal)."""

    expressions_dropped: int = 0
    tendencies_dropped: int = 0
    duplicates_dropped: int = 0
    sparse_trimmed: int = 0
    # duplicates_dropped = exact_duplicates + near_duplicates (the first is identical text, the second an entry
    # whose every point is already made by another entry).
    exact_duplicates: int = 0
    near_duplicates: int = 0
    raw_entries: int = 0
    raw_tendencies: int = 0
    sparse: bool = False
    # What was removed and why, WITH the text, for the operator's evaluation script only. In memory; never logged,
    # never stored, never part of as_dict().
    removed: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, int]:
        return {k: int(v) for k, v in self.__dict__.items() if k != "removed"}


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
    adj.removed += [{"field": "typical_expressions", "reason": "not_verbatim", "text": q}
                    for q in data["typical_expressions"] if not is_verbatim(q, description)]
    adj.expressions_dropped = len(data["typical_expressions"]) - len(kept)
    data["typical_expressions"] = kept

    # 2. Every contextual tendency must carry a verbatim quote that supports it.
    if require_evidence:
        ctx = [c for c in data["context_tendencies"] if is_verbatim(c.get("evidence", ""), description)]
        adj.removed += [{"field": "context_tendencies", "reason": "no_verbatim_evidence",
                         "text": f'{c["context"]}: {c["tendency"]}'}
                        for c in data["context_tendencies"] if not is_verbatim(c.get("evidence", ""), description)]
        adj.tendencies_dropped = len(data["context_tendencies"]) - len(ctx)
        if adj.raw_tendencies and adj.tendencies_dropped * 2 > adj.raw_tendencies:
            raise _reject("ungrounded_context")  # most of it cites nothing real: do not save a patched remainder
        data["context_tendencies"] = ctx

    # 3. Duplicates. (a) Identical text anywhere (traits, guidance, uncertainties, expressions): first one stays.
    seen: set[str] = set()

    def fresh(text: str, where: str) -> bool:
        key = _core(text)
        if key in seen:
            adj.exact_duplicates += 1
            adj.removed.append({"field": where, "reason": "exact_duplicate", "text": text})
            return False
        seen.add(key)
        return True

    data["typical_expressions"] = [q for q in data["typical_expressions"] if fresh(q, "typical_expressions")]
    for f in ITEM_FIELDS:
        data[f] = [i for i in data[f] if fresh(i["text"], f)]
    for f in ("behavioural_guidance", "uncertainties"):
        data[f] = [s_ for s_ in data[f] if fresh(s_, f)]

    # (b) Same observation worded differently: an entry is removed only if another entry already says all of it
    #     (see _covers). Items are compared across sections and against the evidence-backed context tendencies, which
    #     are the home for situational behaviour and are never removed because of an item. Guidance is compared with
    #     guidance and uncertainties with uncertainties only: they have a different job from a trait.
    ctx_sets = [_tokens(f'{c["context"]} {c["tendency"]}') for c in data["context_tendencies"]]
    flat = [(f, n, i["text"]) for f in ITEM_FIELDS for n, i in enumerate(data[f])]
    sets = [_tokens(t) for _, _, t in flat]
    drop: dict[tuple[str, int], tuple[str, str]] = {}
    for a, (f, n, _text) in enumerate(flat):
        for cs, c in zip(ctx_sets, data["context_tendencies"], strict=True):
            if _covers(cs, sets[a]):
                drop[(f, n)] = ("context_tendencies", f'{c["context"]}: {c["tendency"]}')
                break
        else:
            for b, (f2, _n2, text2) in enumerate(flat):
                if b != a and _covers(sets[b], sets[a]) and (sets[b] != sets[a] or b < a):
                    drop[(f, n)] = (f2, text2)
                    break
    for f in ITEM_FIELDS:
        kept_items = []
        for n, i in enumerate(data[f]):
            if (f, n) in drop:
                adj.near_duplicates += 1
                adj.removed.append({"field": f, "reason": "near_duplicate", "text": i["text"],
                                    "covered_by_field": drop[(f, n)][0], "covered_by": drop[(f, n)][1]})
            else:
                kept_items.append(i)
        data[f] = kept_items
    for f in ("behavioural_guidance", "uncertainties"):
        sets_f = [_tokens(t) for t in data[f]]
        keep: list[str] = []
        for a, t in enumerate(data[f]):
            other = next((b for b in range(len(data[f])) if b != a and _covers(sets_f[b], sets_f[a])
                          and (sets_f[b] != sets_f[a] or b < a)), None)
            if other is None:
                keep.append(t)
            else:
                adj.near_duplicates += 1
                adj.removed.append({"field": f, "reason": "near_duplicate", "text": t, "covered_by_field": f,
                                    "covered_by": data[f][other]})
        data[f] = keep
    adj.duplicates_dropped = adj.exact_duplicates + adj.near_duplicates

    # 4. Sparse input: bounded size. Extra uncertainties/guidance are removed; anything still over budget means the
    #    model invented facts, which cannot be fixed by removal.
    if adj.sparse:
        for f, cap in (("uncertainties", SPARSE_MAX_UNCERTAINTIES), ("behavioural_guidance", SPARSE_MAX_GUIDANCE)):
            adj.sparse_trimmed += max(0, len(data[f]) - cap)
            adj.removed += [{"field": f, "reason": "sparse_limit", "text": t} for t in data[f][cap:]]
            data[f] = data[f][:cap]

    result = CharacterProfile.model_validate(data)
    if adj.sparse and entry_count(result) > SPARSE_MAX_ENTRIES:
        raise _reject("sparse_overfilled")

    # 5. Unsupported sensitive attributes. The summary is part of the output and is checked too.
    if sensitive_violations(result.model_dump_json(), description):
        raise _reject("unsupported_sensitive")

    log.info("grounded raw_entries=%d kept_entries=%d expr_dropped=%d ctx_dropped=%d dup_dropped=%d near=%d "
             "trimmed=%d",
             adj.raw_entries, entry_count(result), adj.expressions_dropped, adj.tendencies_dropped,
             adj.duplicates_dropped, adj.near_duplicates, adj.sparse_trimmed)
    return result, adj

