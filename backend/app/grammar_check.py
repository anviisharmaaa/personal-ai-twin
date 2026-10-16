# ruff: noqa: E501
"""A conservative classifier for gendered Hindi / Hinglish / Urdu forms, used by tests and the live evaluation.

Every gender-marked participle, adjective or habitual/future verb it finds is given a ROLE:
  self       it describes the speaker   ("main soch rahi hoon", "(kar raha hoon)", "karungi")
  user       it describes the addressee ("tum thak gaye ho", "aap aayi thin")
  other      it describes a third party ("wo thak gaya hai")
  quoted     it is inside quotation marks (somebody else's words; never judged)
  ambiguous  it agrees with a noun/event/feeling or its referent cannot be told ("yaad aa rahi hai", "din lamba tha",
             "maine dekha", "mujhe neend aa gayi", "baat thi")
Only `self` and `user` forms are ever judged, and only when the evidence is certain enough:
  * a following first-person copula ("hoon/hun") makes the form the speaker's, "ho" makes it the addressee's, whatever
    came before;
  * "hai/hain/tha/thi" and bare past forms take the nearest subject pronoun (main / tum, tu, aap / wo, ye ...) within a
    short window, and are ambiguous otherwise;
  * dative/possessive/ergative openers (mujhe, tumhari, maine, usne ...) make the clause agree with a noun or object, so
    nothing after them counts;
  * "ho/lag/mil + raha/rahi/gaya/gayi" is the experiencer construction ("tumhari yaad aa rahi hai") and is ambiguous;
  * "tha/thi" on their own count only right after a participle or within two words of the subject pronoun.
Anything it cannot classify is reported as ambiguous or ignored, never as a mistake. It reads whole words in Roman,
Devanagari and (a few) Arabic-script spellings. Limits: no real parsing, so unusual word order, names as subjects,
code-mixed English clauses and long-distance agreement can be missed (not misjudged).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

FEM, MASC = "female", "male"
SELF, USER, OTHER, QUOTED, AMBIGUOUS = "self", "user", "other", "quoted", "ambiguous"

# form -> (gender, plural). Plural/honorific -e forms are never judged for the speaker (first person singular).
_PART: dict[str, tuple[str, bool]] = {}
for _stem, _m, _f, _p in [
    ("rah", "raha", "rahi", "rahe"), ("rah", "rha", "rhi", "rhe"), ("ga", "gaya", "gayi", "gaye"), ("ga", "gya", "gyi", "gye"),
    ("aa", "aaya", "aayi", "aaye"), ("a", "aya", "ayi", "aye"), ("hu", "hua", "hui", "hue"), ("thak", "thaka", "thaki", "thake"),
    ("akel", "akela", "akeli", "akele"), ("so", "soya", "soyi", "soye"), ("baith", "baitha", "baithi", "baithe"),
    ("kho", "khoya", "khoyi", "khoye"), ("dar", "dara", "dari", "dare"), ("ghabra", "ghabraya", "ghabrayi", "ghabraye"),
    ("sharma", "sharmaya", "sharmayi", "sharmaye"), ("bhag", "bhaga", "bhagi", "bhage"), ("nikl", "nikla", "nikli", "nikle"),
    ("bhookh", "bhookha", "bhookhi", "bhookhe"), ("pyaas", "pyaasa", "pyaasi", "pyaase"), ("chhup", "chhupa", "chhupi", "chhupe"),
    ("ruk", "ruka", "ruki", "ruke"), ("ut", "utha", "uthi", "uthe"), ("gir", "gira", "giri", "gire"),
    ("jaag", "jaaga", "jaagi", "jaage"), ("mud", "muda", "mudi", "mude"), ("pahunch", "pahuncha", "pahunchi", "pahunche"),
]:
    _PART[_m] = (MASC, False)
    _PART[_f] = (FEM, False)
    _PART[_p] = (MASC, True)
_PART["gai"] = (FEM, False)
_PART["gayee"] = (FEM, False)
_AUX = {"tha": (MASC, False), "thi": (FEM, False), "the": (MASC, True), "thin": (FEM, True)}
_NOT_VERBS = {"dosti", "shakti", "mukti", "jyoti", "prakriti", "sanskriti", "mitti", "kirti", "ichchhukta", "sabhyata", "bhakti", "ruchi"}
_HABIT = re.compile(r"^([a-z]{2,})(ta|ti|te)$")
_FUTURE = re.compile(r"^[a-z]{2,}(unga|ungi)$")  # first person singular future: karunga / karungi

_SELF = {"main", "mai"}
_USER = {"tum", "tu", "aap"}
_OTHER = {"wo", "woh", "vo", "voh", "vah", "ye", "yeh", "wahi", "yahi", "log", "sab", "koi", "kaun", "hum", "ham"}
_BLOCK = {  # ergative / dative openers: the clause agrees with an object or noun, not with a pronoun subject
    "maine", "tumne", "tune", "usne", "unhone", "humne", "aapne", "kisne", "mujhe", "mujhko", "tumhe", "tumhein", "tujhe",
    "hamein", "humein", "usse", "isse", "ise", "use",
}
_POSS = {  # possessives block only when no subject has been seen yet ("meri yaad aayi"), never after "main ..."
    "mera", "meri", "mere", "tumhara", "tumhari", "tumhare", "tera", "teri", "tere", "uska", "uski", "uske", "humari",
    "hamara", "hamari", "unka", "unki", "unke", "apna", "apni", "apne",
}
_ADV = {"bhi", "to", "toh", "hi", "kal", "wahin", "yahin", "wahan", "vahan", "yahan", "tab", "bahut", "kaafi", "bas", "abhi", "pehle", "tabhi"}
_COP_SELF = {"hoon", "hun", "hu", "hoo", "hon"}
_COP_3 = {"hai", "hain", "hoga", "hogi", "honge"}
_COP_USER = {"ho"}
_PAST_AUX = {"tha", "thi", "the", "thin"}
_EXPERIENCER_PREV = {"ho", "lag", "mil", "mila", "chal", "pad"}
_WINDOW = 7

_DEVANAGARI = {
    "मैं": "main", "मै": "main", "रहा": "raha", "रही": "rahi", "रहे": "rahe", "गया": "gaya", "गयी": "gayi", "गई": "gayi",
    "गये": "gaye", "गए": "gaye", "आया": "aaya", "आई": "aayi", "आयी": "aayi", "आए": "aaye", "था": "tha", "थी": "thi", "थे": "the",
    "हूँ": "hoon", "हूं": "hoon", "हुआ": "hua", "हुई": "hui", "हुए": "hue", "थका": "thaka", "थकी": "thaki", "थके": "thake",
    "अकेला": "akela", "अकेली": "akeli", "तुम": "tum", "तू": "tu", "आप": "aap", "वो": "wo", "वह": "wo", "ये": "ye", "यह": "yeh",
    "करता": "karta", "करती": "karti", "सोचता": "sochta", "सोचती": "sochti", "जाता": "jaata", "जाती": "jaati",
    "बैठा": "baitha", "बैठी": "baithi", "सोया": "soya", "सोयी": "soyi", "सोई": "soyi", "हो": "ho", "है": "hai", "हैं": "hain",
    "मैंने": "maine", "तुमने": "tumne", "मुझे": "mujhe", "तुम्हें": "tumhe", "मेरी": "meri", "मेरा": "mera", "तुम्हारी": "tumhari",
}
_ARABIC = {"میں": "main", "رہا": "raha", "رہی": "rahi", "رہے": "rahe", "گیا": "gaya", "گئی": "gayi", "گئے": "gaye", "تھا": "tha",
           "تھی": "thi", "تھے": "the", "ہوں": "hoon", "ہے": "hai", "ہو": "ho", "تم": "tum", "آپ": "aap", "وہ": "wo",
           "تھکا": "thaka", "تھکی": "thaki", "مجھے": "mujhe", "میں نے": "maine"}
_QUOTE = re.compile(r"[\"“”«»]([^\"“”«»]*)[\"“”«»]")
_BREAK = re.compile(r"[.!?;,:\n()\[\]*—–…]+|\s-\s|\b(?:aur|lekin|par|magar|kyunki|kyuki)\b")


@dataclass(frozen=True)
class Mark:
    form: str
    gender: str
    role: str
    clause: str


@dataclass(frozen=True)
class Result:
    ok: bool
    expected: str
    marks: tuple[Mark, ...]          # forms judged for this role
    violations: tuple[Mark, ...]
    ambiguous: tuple[Mark, ...] = ()
    unjudged: tuple[Mark, ...] = ()  # other / quoted forms, shown for transparency

    @property
    def has_evidence(self) -> bool:
        return bool(self.marks)

    @property
    def masculine_default(self) -> tuple[Mark, ...]:
        """Masculine forms where masculine was not configured: the failure to watch for with neutral/unspecified identities."""
        return tuple(m for m in self.violations if m.gender == MASC) if self.expected not in (MASC,) else ()


def _tok(w: str) -> str:
    return _DEVANAGARI.get(w) or _ARABIC.get(w) or w


def _words(text: str) -> list[str]:
    return [_tok(w) for w in re.findall(r"[\wऀ-ॿ؀-ۿ]+", text.lower())]


def _by_subject(subj: str | None, gap: int, limit: int) -> str:
    if subj is None or gap > limit:
        return AMBIGUOUS
    return {"s": SELF, "u": USER, "o": OTHER}.get(subj, AMBIGUOUS)


def _classify_clause(clause: str) -> list[Mark]:
    toks = _words(clause)
    out: list[Mark] = []
    subj: str | None = None   # s / u / o / b (blocked)
    at = -99
    i = 0
    while i < len(toks):
        t = toks[i]
        if t in _SELF:
            subj, at = "s", i
        elif t in _USER:
            subj, at = "u", i
        elif t in _OTHER:
            subj, at = "o", i
        elif t in _BLOCK or (t in _POSS and subj is None):
            subj, at = "b", i
        elif t in _PART or t in _AUX or _HABIT.match(t) and t not in _NOT_VERBS or _FUTURE.match(t):
            gender, plural, kind = None, False, "part"
            if t in _PART:
                gender, plural = _PART[t]
            elif t in _AUX:
                gender, plural = _AUX[t]
                kind = "aux"
            elif _FUTURE.match(t):
                gender, kind = (FEM if t.endswith("ungi") else MASC), "future"
            else:
                m = _HABIT.match(t)
                assert m
                gender = FEM if m.group(2) == "ti" else MASC
                plural, kind = m.group(2) == "te", "habit"
            gap = i - at
            nxt = toks[i + 1] if i + 1 < len(toks) else ""
            nxt2 = toks[i + 2] if i + 2 < len(toks) else ""
            prev = toks[i - 1] if i > 0 else ""
            role = AMBIGUOUS
            if kind == "future":
                role = SELF
            elif kind == "aux":
                prev_is_part = prev in _PART or bool(_HABIT.match(prev))
                if prev_is_part:
                    i += 1
                    continue                                   # already judged together with its participle
                between = toks[at + 1:i] if at >= 0 else []
                if subj in ("s", "u") and 0 < gap <= 3 and all(w in _ADV for w in between):
                    role = _by_subject(subj, gap, 3)
            else:
                cop = nxt2 if nxt in _PAST_AUX else nxt        # "raha tha hoon" is rare; "raha tha" is the past form
                past = nxt in _PAST_AUX
                if past and not (nxt2 in _COP_SELF or nxt2 in _COP_USER):
                    cop = ""
                if kind == "habit" and (prev in _EXPERIENCER_PREV or t in {"hota", "hoti"}):
                    role = AMBIGUOUS
                elif nxt in _COP_SELF or (past and nxt2 in _COP_SELF):
                    role = SELF
                elif nxt in _COP_USER or (past and nxt2 in _COP_USER):
                    role = USER if subj != "s" else AMBIGUOUS
                elif prev in _EXPERIENCER_PREV and t in _PART and t[:2] in ("ra", "rh", "ga", "gy", "hu"):
                    role = AMBIGUOUS                            # "yaad aa rahi hai", "neend aa gayi", "theek ho gaya"
                elif nxt in _COP_3 and not past:
                    role = _by_subject(subj, gap, 3) if subj in ("u", "o") else AMBIGUOUS
                elif past or cop == "":
                    role = _by_subject(subj, gap, _WINDOW if past else 3) if subj in ("s", "u", "o") else AMBIGUOUS
                if subj == "b" and role not in (SELF, USER):
                    role = AMBIGUOUS
                if plural and role == SELF:
                    role = AMBIGUOUS
            out.append(Mark(t, gender or MASC, role, clause.strip()))
        i += 1
    return out


def classify(text: str) -> list[Mark]:
    """Every gender-marked form with its role. Quoted spans are reported as `quoted` and never judged."""
    marks: list[Mark] = []
    for q in _QUOTE.findall(text):
        marks.extend(Mark(m.form, m.gender, QUOTED, m.clause) for c in _BREAK.split(q.lower()) if c.strip() for m in _classify_clause(c))
    unquoted = _QUOTE.sub(" , ", text)
    for c in _BREAK.split(unquoted.lower()):
        if c and c.strip():
            marks.extend(_classify_clause(c))
    return marks


def self_marks(text: str) -> list[Mark]:
    return [m for m in classify(text) if m.role == SELF]


def user_marks(text: str) -> list[Mark]:
    return [m for m in classify(text) if m.role == USER]


def _check(text: str, expected: str, role: str) -> Result:
    allm = classify(text)
    marks = tuple(m for m in allm if m.role == role)
    bad = tuple(m for m in marks if m.gender != expected) if expected in (FEM, MASC) else marks
    return Result(not bad, expected, marks, bad, tuple(m for m in allm if m.role == AMBIGUOUS),
                  tuple(m for m in allm if m.role in (OTHER, QUOTED) or (m.role in (SELF, USER) and m.role != role)))


def check_self_gender(text: str, expected: str) -> Result:
    """expected 'female' / 'male': any self-form of the other gender is a violation. Anything else ('neutral',
    'non_binary', 'unspecified'): any gendered self-form is reported (see Result.masculine_default for the worst kind)."""
    return _check(text, expected, SELF)


def check_user_form(text: str, expected: str) -> Result:
    """expected 'female' / 'male' = the forms the character should use about the user; otherwise none should be asserted."""
    return _check(text, expected, USER)
