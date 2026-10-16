# ruff: noqa: E501
"""Who the character IS, for grammar and self-reference: an explicit gender and pronouns chosen by the creator.

Stored inside the character's existing `appearance` JSON (keys `gender`, `pronouns`), so no database migration is needed.
Precedence, highest first, and why it is predictable:
  1. the creator's explicit selection (this module);
  2. explicit identity wording in the original description (used only when nothing is selected);
  3. the generated profile (supplementary, never consulted for gender).
If a selection and the description disagree, the SELECTION governs grammar and self-reference and the description still
governs everything else; the prompt says so and the server logs the conflict (never silently merged).
Gender never implies personality, interests, emotional behaviour or relationship roles.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

GENDERS = ("female", "male", "non_binary", "unspecified")
DEFAULT_PRONOUNS = {"female": "she/her", "male": "he/him", "non_binary": "they/them", "unspecified": ""}
LABEL = {"female": "female (a woman)", "male": "male (a man)", "non_binary": "non-binary"}


@dataclass(frozen=True)
class Identity:
    gender: str = "unspecified"
    pronouns: str = ""

    @property
    def selected(self) -> bool:
        return self.gender != "unspecified" or bool(self.pronouns)


def identity_of(twin: dict[str, Any] | None) -> Identity:
    """Read the selection from the character record that the conversation is bound to (never from a request)."""
    ap = (twin or {}).get("appearance") or {}
    g = ap.get("gender")
    gender = g if g in GENDERS else "unspecified"
    pronouns = str(ap.get("pronouns") or "").strip()[:40]
    if gender != "unspecified" and not pronouns:
        pronouns = DEFAULT_PRONOUNS[gender]
    return Identity(gender, pronouns)


# ---- description conflict detection (a hint, logged and told to the model; the selection still wins) -------------------

_FEM = re.compile(r"\b(she|her|hers|herself|woman|girl|lady|mother|sister|daughter|wife|girlfriend|aunt)\b", re.I)
_MASC = re.compile(r"\b(he|him|his|himself|man|boy|gentleman|father|brother|son|husband|boyfriend|uncle)\b", re.I)


def description_leaning(description: str) -> str:
    """'female' / 'male' when the description's English wording clearly points one way, else 'unclear'."""
    f, m = len(_FEM.findall(description)), len(_MASC.findall(description))
    if f >= 2 and f >= 2 * m:
        return "female"
    if m >= 2 and m >= 2 * f:
        return "male"
    return "unclear"


def description_conflicts(identity: Identity, description: str) -> bool:
    lean = description_leaning(description)
    return identity.gender in ("female", "male") and lean in ("female", "male") and lean != identity.gender


# ---- prompt text ----------------------------------------------------------------------------------------------------

_FORMS = {
    "female": ("feminine", "Hindi/Urdu/Hinglish: \"main soch rahi hoon\", \"main thak gayi hoon\", \"main aayi thi\""),
    "male": ("masculine", "Hindi/Urdu/Hinglish: \"main soch raha hoon\", \"main thak gaya hoon\", \"main aaya tha\""),
}

_SHARED = """\
Apply this to EVERY part of EVERY reply, in whatever language the user writes:
- Whenever the language marks the speaker's gender (verbs, participles, adjectives and self-descriptions, as in Hindi, \
Urdu and Hinglish, and also Spanish, French, Arabic, Russian and others), use the forms that agree with this identity \
when you speak about yourself, consistently. That includes jokes, asides in parentheses, stage directions, role-play, \
emotional outbursts and anything you quote yourself saying.
- Do not fall back to the masculine by habit, because the user's messages or earlier replies in this conversation used \
other forms, or because the model's default is masculine. Earlier replies may contain wrong forms: do not copy them.
- Agreement follows WHO the word refers to. Forms about the user or other people agree with them, not with you, and the \
grammatical gender of a noun is a fact about the noun, not about you.
- Where the language does not mark gender (English first person, for example), say nothing extra and add no gender \
markers. Never make the speech awkward to show gender.
- Gender says nothing about personality, interests, emotions, abilities or relationship roles. Those come only from \
the original description."""


def identity_block(idn: Identity, description: str = "") -> str:
    """The first-class identity instruction placed before the description. Empty selection gets an honest 'not selected'."""
    if not idn.selected:
        lean = description_leaning(description)
        hint = (f" The description's own wording points to {lean} ({'she/her' if lean == 'female' else 'he/him'}); follow it."
                if lean != "unclear" else
                " The description does not clearly say. Do not guess and do not default to masculine: where the language "
                "forces a gendered form for yourself, follow any pronouns or gendered wording the description uses; if there "
                "are none, rephrase to avoid gendered self-reference (for example, in Hindi use constructions such as "
                "\"mujhe yaad hai\" or \"mera mann hai\" instead of a verb that has to be masculine or feminine).")
        return ("\n<character_identity> NOT SELECTED\nThe creator has not chosen a gender or pronouns for this character." + hint
                + "\n</character_identity>")
    lines = ["\n<character_identity> AUTHORITATIVE (explicitly selected by the creator; it outranks any other source for "
             "grammar and self-reference)"]
    if idn.gender in LABEL:
        lines.append(f"Gender: {LABEL[idn.gender]}.")
    lines.append(f"Pronouns: {idn.pronouns or 'as the description uses them'}.")
    if idn.gender in _FORMS:
        word, examples = _FORMS[idn.gender]
        lines.append(f"Whenever the language marks gender, speak as yourself with {word} forms. Agreement pattern, not "
                     f"sentences to repeat ({examples}).")
    elif idn.gender == "non_binary":
        lines.append("Refer to yourself and expect to be referred to with these pronouns. In languages where a verb or "
                     "adjective for yourself must be masculine or feminine (Hindi, Urdu, Hinglish), prefer wording that "
                     "avoids it (\"mujhe yaad hai\", \"mera mann hai\", \"ho raha hai\"); if it cannot be avoided, use "
                     "the form the description indicates, and never default to masculine.")
    lines.append(_SHARED)
    if description_conflicts(idn, description):
        lines.append("Note: the original description's wording seems to use different pronouns. The selection above "
                     "governs how you refer to yourself and are referred to; the description still governs who you are.")
    lines.append("</character_identity>")
    return "\n".join(lines)


def identity_reminder(idn: Identity) -> str:
    if idn.gender == "female":
        return ("Identity reminder: you are a woman (she/her unless the creator chose otherwise). Use feminine forms for "
                "yourself wherever the language marks gender, in every part of the reply.")
    if idn.gender == "male":
        return ("Identity reminder: you are a man (he/him unless the creator chose otherwise). Use masculine forms for "
                "yourself wherever the language marks gender, in every part of the reply.")
    if idn.gender == "non_binary":
        return (f"Identity reminder: your pronouns are {idn.pronouns or 'they/them'}. Do not default to masculine forms; "
                "avoid gendered self-reference where the language allows.")
    if idn.pronouns:
        return f"Identity reminder: your pronouns are {idn.pronouns}. Do not default to masculine forms."
    return "Identity reminder: no gender is selected. Do not default to masculine forms for yourself."
