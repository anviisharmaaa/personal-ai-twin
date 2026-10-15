"""Conversation-driven learning: extraction of memory CANDIDATES from the user's own messages.

What this is: application-level retrieval and adaptation. A candidate is a proposal; it becomes a memory only when the
user approves it. Nothing here fine-tunes or retrains a model, and assistant text is never evidence.

Rules enforced in `validate_candidates` (pure, no I/O, so they are unit-tested without a model):
- every supporting quote is a verbatim span of one of the USER's messages (assistant messages are context only);
- the statement must actually share content with its quotes;
- a repeated pattern needs at least two different messages;
- hypotheticals, role-play and passing moods are dropped unless the user asked to be remembered;
- sensitive attributes the user did not state are dropped (same check as the character profile);
- ideas the user already rejected, or that already exist, are dropped by fingerprint.
Nothing here logs message text; callers log counts and codes only.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.chat import ChatError
from app.grounding import _tokens, is_verbatim, sensitive_violations

CATEGORIES = ("fact", "preference", "boundary", "communication_style", "trait", "context_behaviour", "correction")
EVIDENCE_TYPES = ("explicit_statement", "correction", "memory_request", "repeated_pattern")
# Evidence quality, highest first. No numeric "confidence": the category says what kind of evidence it is.
EVIDENCE_RANK = {"memory_request": 4, "correction": 3, "explicit_statement": 2, "repeated_pattern": 1}
SECTION_FOR_CATEGORY = {"communication_style": "speaking_style", "trait": "core_traits",
                        "boundary": "boundaries_and_careful_topics", "context_behaviour": "response_patterns"}
PROPOSAL_EVIDENCE = ("correction", "repeated_pattern")
MIN_QUOTE_CHARS = 8
MAX_STATEMENT_CHARS = 240

_HYPOTHETICAL = re.compile(
    r"\b(imagine|pretend|what if|let'?s say|suppose|role-?play|hypothetical(?:ly)?|in this story|for the sake of)\b",
    re.IGNORECASE)
_PASSING = re.compile(
    r"\b(today|right now|this morning|tonight|at the moment|just now)\b.{0,40}\b(i'?m|i am|feeling|feel)\b|"
    r"\b(i'?m|i am|feeling)\b.{0,30}\b(today|right now|at the moment)\b", re.IGNORECASE)
_REMEMBER = re.compile(r"\b(remember|keep in mind|don'?t forget|note that|from now on)\b", re.IGNORECASE)


_MARKERS = frozenset(('¬', '+', '-', 'instead'))


def _sentence_of(message: str, quote: str) -> str:
    """The sentence of `message` that contains `quote` (the whole message if it can't be located)."""
    low, q = message.casefold(), quote.casefold().strip(" .,;:!?'\"")
    at = low.find(q)
    if at < 0:
        return message
    start = max(low.rfind(c, 0, at) for c in ".!?\n") + 1
    ends = [i for i in (low.find(c, at + len(q)) for c in ".!?\n") if i >= 0]
    return message[start:(min(ends) + 1) if ends else len(message)]


def fingerprint(statement: str) -> str:
    """Order- and wording-insensitive identity of an idea. Stored on rejected/deleted ideas instead of their text."""
    return hashlib.sha256(" ".join(sorted(_tokens(statement))).encode()).hexdigest()[:32]


def overlap(a: str, b: str) -> float:
    """Share of the smaller statement's content words that also appear in the other (0..1)."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


@dataclass
class Rejections:
    counts: dict[str, int] = field(default_factory=dict)

    def add(self, why: str) -> None:
        self.counts[why] = self.counts.get(why, 0) + 1


def validate_candidates(raw: object, user_messages: dict[str, dict[str, Any]], known_fingerprints: set[str],
                        limit: int) -> tuple[list[dict[str, Any]], Rejections]:
    """`user_messages` maps the label shown to the model (m1, m2, …) to the stored USER message. Anything the model
    returns about another label (including an assistant message) has no entry here and is therefore refused."""
    rej = Rejections()
    out: list[dict[str, Any]] = []
    seen = set(known_fingerprints)
    items = raw if isinstance(raw, list) else []
    if not isinstance(raw, list):
        rej.add("not_a_list")
    all_user_text = "\n".join(m["content"] for m in user_messages.values())
    user_messages_by_id = {m["id"]: m["content"] for m in user_messages.values()}
    for it in items:
        if len(out) >= limit:
            rej.add("over_limit")
            break
        if not isinstance(it, dict):
            rej.add("malformed")
            continue
        statement = str(it.get("statement", "")).strip()
        category, evidence_type = it.get("category"), it.get("evidence_type")
        scope = str(it.get("scope") or "").strip()[:160]
        quotes_in = it.get("quotes")
        if not statement or len(statement) > MAX_STATEMENT_CHARS or category not in CATEGORIES \
                or evidence_type not in EVIDENCE_TYPES or not isinstance(quotes_in, list) or not quotes_in:
            rej.add("malformed")
            continue
        supporting: list[dict[str, str]] = []
        ok = True
        for q in quotes_in[:4]:
            msg = user_messages.get(str(q.get("message", ""))) if isinstance(q, dict) else None
            text = str(q.get("quote", "")).strip() if isinstance(q, dict) else ""
            if msg is None:
                rej.add("not_a_user_message")
                ok = False
                break
            if len(text) < MIN_QUOTE_CHARS or not is_verbatim(text, msg["content"]):
                rej.add("quote_not_verbatim")
                ok = False
                break
            supporting.append({"message_id": msg["id"], "quote": text})
        if not ok:
            continue
        distinct = {s["message_id"] for s in supporting}
        if evidence_type == "repeated_pattern" and len(distinct) < 2:
            rej.add("pattern_needs_two_messages")
            continue
        joined = " ".join(s["quote"] for s in supporting)
        # Judge the whole sentence each quote came from: "Imagine I hate…" must not be rescued by quoting only "hate…".
        context = " ".join(_sentence_of(user_messages_by_id[s["message_id"]], s["quote"]) for s in supporting)
        if evidence_type != "memory_request":
            if _HYPOTHETICAL.search(context):
                rej.add("hypothetical_or_roleplay")
                continue
            if _PASSING.search(context):
                rej.add("passing_mood")
                continue
        elif not _REMEMBER.search(context):
            rej.add("no_memory_request")
            continue
        words = _tokens(statement) - _MARKERS      # polarity markers alone never count as shared content
        shared = words & _tokens(joined)
        if not shared or len(shared) / len(words) < 0.25:
            rej.add("statement_not_supported")
            continue
        if sensitive_violations(statement, all_user_text):
            rej.add("sensitive_not_stated")
            continue
        fp = fingerprint(statement)
        if fp in seen:
            rej.add("already_known_or_rejected")
            continue
        seen.add(fp)
        out.append({"statement": statement, "category": category, "scope": scope, "evidence_type": evidence_type,
                    "supporting": supporting, "fingerprint": fp})
    return out, rej


SYSTEM = """You review a conversation to propose things worth remembering about the USER (the human writing the
messages labelled USER). Output JSON only.

Rules:
- Use ONLY what the USER wrote. Messages labelled ASSISTANT are context and are NEVER evidence.
- Each item needs 1-3 quotes copied word for word from USER messages, with the message label (m1, m2, ...).
- Propose only durable facts, preferences, boundaries, ways of speaking, traits, or corrections the user made about
  how the twin should behave. Skip small talk, one-off moods, hypotheticals, role-play and anything uncertain.
- Never infer health, religion, sexuality, ethnicity, politics or similar unless the user stated it.
- statement: one short third-person sentence. category is one of: %s.
- evidence_type: explicit_statement (user said it), correction (user corrected the twin), memory_request (user asked
  to be remembered), repeated_pattern (shown in 2+ different messages).
- If nothing qualifies return {"memories": []}.
Return {"memories":[{"statement":"","category":"","scope":"","evidence_type":"",
"quotes":[{"message":"m1","quote":""}]}]}
""" % ", ".join(CATEGORIES)


def render_conversation(messages: list[dict[str, Any]]) -> tuple[str, dict[str, dict[str, Any]]]:
    """Label complete messages m1..mN; only USER messages are returned as citable."""
    labelled: dict[str, dict[str, Any]] = {}
    lines = []
    for i, m in enumerate(messages, 1):
        label = f"m{i}"
        who = "USER" if m["role"] == "user" else "ASSISTANT"
        text = m["content"].replace("</conversation>", "")
        lines.append(f"[{label}] {who}: {text}")
        if m["role"] == "user":
            labelled[label] = m
    return "<conversation>\n" + "\n".join(lines) + "\n</conversation>", labelled


class Extractor(Protocol):
    configured: bool

    async def extract(self, conversation: str) -> object: ...


@dataclass
class UnavailableExtractor:
    code: str
    message: str
    configured: bool = False

    async def extract(self, conversation: str) -> object:  # pragma: no cover - routes stop earlier
        raise ChatError(self.code, self.message, 503)


class OllamaExtractor:
    """One non-streaming JSON call to the local model. Same loopback guard as chat and analysis."""

    configured = True

    def __init__(self, base_url: str, model: str, timeout_s: float, max_output_tokens: int, *,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._url = base_url.strip().rstrip("/") + "/chat/completions"
        self._model, self._timeout, self._max = model, timeout_s, max_output_tokens
        self._transport = transport

    async def extract(self, conversation: str) -> object:
        payload = {"model": self._model, "stream": False, "temperature": 0.1, "max_tokens": self._max,
                   "response_format": {"type": "json_object"}, "reasoning_effort": "none",
                   "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": conversation}]}
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as c:
                r = await c.post(self._url, json=payload)
        except httpx.ConnectError as e:
            raise ChatError("local_unavailable", "Ollama isn't running or couldn't be reached.", 503) from e
        except httpx.TimeoutException as e:
            raise ChatError("timeout", "The local model took too long.", 504) from e
        except httpx.HTTPError as e:
            raise ChatError("interrupted", "The connection to the local model was interrupted.", 502,
                            type(e).__name__) from e
        if r.status_code in (400, 404) and "not found" in r.text.lower():
            raise ChatError("local_model_missing", "The configured Ollama model isn't installed.", 503)
        if r.status_code >= 400:
            raise ChatError("provider_error", "The local model returned an error.", 502, f"http={r.status_code}")
        try:
            content = r.json()["choices"][0]["message"]["content"]
            data = json.loads(content)
        except (KeyError, IndexError, ValueError, TypeError) as e:
            raise ChatError("not_json", "The local model's answer wasn't usable.", 502) from e
        if not isinstance(data, dict) or "memories" not in data:
            raise ChatError("schema_invalid", "The local model's answer had the wrong shape.", 502)
        return data["memories"]
