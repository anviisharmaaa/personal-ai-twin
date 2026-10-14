"""Personality questionnaire: server is the source of truth for questions and valid answers."""

from typing import Any

NOT_SURE = "not_sure"

QUESTIONS: list[dict[str, Any]] = [
    {"id": "tone", "prompt": "How should your twin generally sound?", "multi": False,
     "options": ["warm", "playful", "calm", "direct", "formal"]},
    {"id": "humour", "prompt": "How much humour feels like you?", "multi": False,
     "options": ["none", "dry", "gentle", "playful"]},
    {"id": "emotional_support", "prompt": "When someone is struggling, what do you usually do?",
     "multi": False, "options": ["listen", "advise", "balanced"]},
    {"id": "directness", "prompt": "How direct are you when you disagree?", "multi": False,
     "options": ["gentle", "balanced", "blunt"]},
    {"id": "values", "prompt": "Which values matter most to you? (up to 3)", "multi": True,
     "max": 3, "options": ["family", "honesty", "curiosity", "kindness", "faith", "ambition",
                           "creativity", "humility", "freedom", "service"]},
    {"id": "boundaries", "prompt": "Are there topics your twin should gently steer away from?",
     "multi": True, "max": 5, "options": ["health", "money", "politics", "religion",
                                          "family_conflict", "grief"]},
]

_BY_ID = {q["id"]: q for q in QUESTIONS}


def validate_answers(answers: dict[str, Any]) -> dict[str, Any]:
    """Return cleaned answers or raise ValueError. Unknown questions/options are rejected."""
    clean: dict[str, Any] = {}
    for qid, value in answers.items():
        q = _BY_ID.get(qid)
        if q is None:
            raise ValueError(f"unknown question: {qid}")
        allowed = set(q["options"]) | {NOT_SURE}
        if q["multi"]:
            if not isinstance(value, list) or len(value) > q.get("max", 3):
                raise ValueError(f"invalid answer for {qid}")
            if any(v not in allowed for v in value):
                raise ValueError(f"invalid option for {qid}")
            clean[qid] = list(dict.fromkeys(value))
        else:
            if not isinstance(value, str) or value not in allowed:
                raise ValueError(f"invalid answer for {qid}")
            clean[qid] = value
    return clean
