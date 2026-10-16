# ruff: noqa: E501
"""A conservative checker for grammatical gender in the SPEAKER's own self-reference in Hindi / Hinglish / Urdu (romanised,
Devanagari and Arabic script via a small token map).

It exists so tests and the live evaluation can catch mistakes such as a female character saying "kar raha hoon".
What it counts as self-reference (and nothing else):
  * a gender-marked participle/adjective whose nearest preceding subject pronoun in the clause is "main" ("main soch rahi hoon"),
  * or one directly followed by the first-person copula "hoon/hun" with no other subject before it ("(... kar raha hoon)"),
  * "tha/thi" only right after such a participle or within three words of "main" (so "baat thi" is not evidence).
What it deliberately ignores: forms whose nearest subject is tum/aap/wo/... (they describe someone else), nouns and their
agreement ("project", "baat"), the ergative "maine ..." (no agreement with the speaker), and quoted speech of others, which a
word-level checker cannot reliably separate (a documented limitation).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

FEM, MASC = "female", "male"

_PARTICIPLE = {  # strong markers: form -> gender
    "raha": MASC, "rahi": FEM, "gaya": MASC, "gayi": FEM, "gai": FEM, "aaya": MASC, "aya": MASC, "aayi": FEM, "ayi": FEM,
    "hua": MASC, "hui": FEM, "gira": MASC, "giri": FEM, "soya": MASC, "soyi": FEM, "baitha": MASC, "baithi": FEM,
    "thaka": MASC, "thaki": FEM, "akela": MASC, "akeli": FEM, "ghabraya": MASC, "ghabrayi": FEM, "dara": MASC, "dari": FEM,
    "sharmaya": MASC, "sharmayi": FEM, "bhaga": MASC, "bhagi": FEM, "khoya": MASC, "khoyi": FEM, "nikla": MASC, "nikli": FEM,
}
_AUX = {"tha": MASC, "thi": FEM}
_HABITUAL_END = re.compile(r"^[a-z]{2,}(ta|ti)$")
_COPULA = {"hoon", "hun", "hu", "hoo"}
_SELF = {"main", "mai", "mein_"}  # "mein" (in) is never a subject
_OTHER = {"tum", "tu", "tumne", "tune", "aap", "wo", "woh", "vo", "voh", "vah", "ye", "yeh", "usne", "unhone", "hum", "ham",
          "log", "sab", "koi", "kaun", "tumhara", "tera"}
_CLAUSE_BREAK = re.compile(r"[.!?;,:\n()\[\]\"“”*—–-]+|\b(?:aur|lekin|par|magar|toh|jab|kyunki|kyuki)\b")

_DEVANAGARI = {  # token -> romanised
    "मैं": "main", "मै": "main", "रहा": "raha", "रही": "rahi", "गया": "gaya", "गयी": "gayi", "गई": "gayi", "आया": "aaya",
    "आई": "aayi", "आयी": "aayi", "था": "tha", "थी": "thi", "हूँ": "hoon", "हूं": "hoon", "हुआ": "hua", "हुई": "hui",
    "थका": "thaka", "थकी": "thaki", "अकेला": "akela", "अकेली": "akeli", "तुम": "tum", "तू": "tu", "आप": "aap", "वो": "wo",
    "वह": "wo", "ये": "ye", "यह": "yeh", "करता": "karta", "करती": "karti", "सोचता": "sochta", "सोचती": "sochti",
    "जाता": "jaata", "जाती": "jaati", "मैंने": "maine",
}
_ARABIC = {"میں": "main", "رہا": "raha", "رہی": "rahi", "گیا": "gaya", "گئی": "gayi", "تھا": "tha", "تھی": "thi",
           "ہوں": "hoon", "تم": "tum", "آپ": "aap", "وہ": "wo", "تھکا": "thaka", "تھکی": "thaki"}


@dataclass(frozen=True)
class Mark:
    form: str
    gender: str
    clause: str


@dataclass(frozen=True)
class Result:
    ok: bool
    expected: str
    marks: tuple[Mark, ...]
    violations: tuple[Mark, ...]

    @property
    def has_evidence(self) -> bool:
        return bool(self.marks)


def _tokens(clause: str) -> list[str]:
    out = []
    for w in re.findall(r"[\wऀ-ॿ؀-ۿ]+", clause.lower()):
        out.append(_DEVANAGARI.get(w) or _ARABIC.get(w) or w)
    return out


def self_marks(text: str) -> list[Mark]:
    marks: list[Mark] = []
    for clause in _CLAUSE_BREAK.split(text.lower()):
        if not clause or not clause.strip():
            continue
        toks = _tokens(clause)
        last_subject: str | None = None
        main_at = -99
        prev_strong = False
        for i, t in enumerate(toks):
            if t in ("main", "mai"):
                last_subject, main_at, prev_strong = "self", i, False
                continue
            if t in _OTHER:
                last_subject, prev_strong = "other", False
                continue
            nxt = toks[i + 1] if i + 1 < len(toks) else ""
            gender = None
            if t in _PARTICIPLE:
                if last_subject == "self" or (last_subject is None and nxt in _COPULA):
                    gender = _PARTICIPLE[t]
                prev_strong = True
            elif t in _AUX:
                if last_subject != "other" and (prev_strong or i - main_at <= 3):
                    if prev_strong or last_subject == "self":
                        gender = _AUX[t]
                prev_strong = False
            elif _HABITUAL_END.match(t) and nxt in _COPULA and last_subject != "other":
                gender = MASC if t.endswith("ta") else FEM
                prev_strong = False
            else:
                prev_strong = False
            if gender:
                marks.append(Mark(t, gender, clause.strip()))
    return marks


def check_self_gender(text: str, expected: str) -> Result:
    """expected: 'female' or 'male' -> any opposite-gender self-mark is a violation.
    'non_binary' / 'unspecified' -> any self-mark of either gender is reported as a violation (nothing was configured to
    support it); callers that allow a described gender should compare against that gender instead."""
    marks = tuple(self_marks(text))
    if expected in (FEM, MASC):
        bad = tuple(m for m in marks if m.gender != expected)
    else:
        bad = marks
    return Result(not bad, expected, marks, bad)


# ---- forms that refer to the USER (the addressee: tum / tu / aap) -------------------------------------------------------
# Agreement with "tum/aap" is masculine in -a/-e ("tum thak gaye ho", "tum aaye the") and feminine in -i ("tum thak gayi ho").
# Only a gender-marked participle/adjective whose nearest preceding subject pronoun is tum/tu/aap counts.

_ADDRESSEE = {"tum", "tu", "tumne", "tune", "aap", "aapne"}
_USER_PART = {
    "raha": MASC, "rahe": MASC, "rahi": FEM, "gaya": MASC, "gaye": MASC, "gayi": FEM, "gai": FEM,
    "aaya": MASC, "aaye": MASC, "aayi": FEM, "hua": MASC, "hue": MASC, "hui": FEM,
    "thaka": MASC, "thake": MASC, "thaki": FEM, "akela": MASC, "akele": MASC, "akeli": FEM,
    "soye": MASC, "soyi": FEM, "baithe": MASC, "baithi": FEM, "khoye": MASC, "khoyi": FEM,
}
_USER_AUX = {"tha": MASC, "the": MASC, "thi": FEM, "thin": FEM}
_USER_COP = {"ho", "hai", "hain"}
_USER_HAB = re.compile(r"^[a-z]{2,}(ta|te|ti)$")


def user_marks(text: str) -> list[Mark]:
    marks: list[Mark] = []
    for clause in _CLAUSE_BREAK.split(text.lower()):
        if not clause or not clause.strip():
            continue
        toks = _tokens(clause)
        subj: str | None = None
        at = -99
        prev_part = False
        for i, t in enumerate(toks):
            if t in _ADDRESSEE:
                subj, at, prev_part = "user", i, False
                continue
            if t in ("main", "mai", "wo", "woh", "vo", "voh", "ye", "yeh", "usne", "hum", "ham", "maine"):
                subj, prev_part = "else", False
                continue
            nxt = toks[i + 1] if i + 1 < len(toks) else ""
            g = None
            if t in _USER_PART:
                if subj == "user":
                    g = _USER_PART[t]
                prev_part = True
            elif t in _USER_AUX:
                if subj == "user" and (prev_part or i - at <= 2):
                    g = _USER_AUX[t]
                prev_part = False
            elif _USER_HAB.match(t) and nxt in _USER_COP and subj == "user":
                g = FEM if t.endswith("ti") else MASC
                prev_part = False
            else:
                prev_part = False
            if g:
                marks.append(Mark(t, g, clause.strip()))
    return marks


def check_user_form(text: str, expected: str) -> Result:
    """expected: 'female' or 'male' = the forms the character should use about the user; 'neutral' = none should be
    asserted. Forms about the character itself (main ...) are ignored here and checked by check_self_gender."""
    marks = tuple(user_marks(text))
    bad = tuple(m for m in marks if m.gender != expected) if expected in (FEM, MASC) else marks
    return Result(not bad, expected, marks, bad)
