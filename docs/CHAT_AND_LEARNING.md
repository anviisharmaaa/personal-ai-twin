# Persistent conversations, streaming and conversation-driven learning (Phase 4)

## Three kinds of knowledge, kept apart

| Kind | Where | Who writes it | Used in a reply |
|---|---|---|---|
| Original description | `twins.character_description` | the user only | yes (as data), never rewritten |
| Current conversation | `messages` | user + model | bounded window (newest first) |
| Approved memories | `memories` | the user, by approving a candidate | yes: a few relevant ones |

Candidates (`memory_candidates`) are proposals. They are **never** in a prompt. Profile refinements
(`profile_proposals` → `character_profiles.profile`, with `profile_revisions` as history) are a second, explicit
user decision on top of a memory.

"Learning" here means saved notes that are looked up and added to the prompt. It is **not** fine-tuning or retraining,
and the product never says it is. Assistant text is never evidence.

## Providers

`CharacterAnalyzer` (structured analysis) is unchanged. Chat has its own `ChatProvider` (`app/chat.py`):
`OllamaChatProvider` (real `stream=true`, loopback-guarded) and a labelled `MockChatProvider`. NVIDIA and OpenAI return
`chat_provider_unsupported` (personal conversations stay off the NVIDIA trial endpoint; paid OpenAI chat is not
switched on). There is no fallback between providers. Learning extraction (`app/learning.py`) runs on Ollama only;
sample mode answers `learning_unavailable_in_sample_mode`.

One local-model job at a time: `ModelGate` (`LOCAL_MODEL_CONCURRENCY`, default 1) is shared by chat replies,
character analysis and learning reviews. A second job is refused at once with `model_busy` (429), never queued silently.

## API

All under `/api/v1`, bearer token required, user id taken from the verified token, every query also filters
`owner_id` (RLS is the second layer).

| Route | Purpose |
|---|---|
| `GET /chat/status` | available / reason / provider / is_sample / model_busy / profile_outdated / limits |
| `GET,POST /conversations`, `PATCH,DELETE /conversations/{id}` | list, create, rename, delete (`?delete_memories=true`) |
| `GET /conversations/{id}/messages` | history; marks a reply cut off by a restart `incomplete/interrupted` |
| `POST /conversations/{id}/messages/stream` | send + stream the reply (SSE) |
| `GET,PUT /learning/preference` | learning consent (default off; `disclosure_version` required to turn on) |
| `POST /conversations/{id}/learning/review` → 202, `GET …/learning` | background review, state, candidates |
| `GET /memory/candidates`, `POST …/{id}/approve`, `POST …/{id}/reject` | review |
| `GET /memories`, `PATCH,DELETE /memories/{id}` | inspect, edit/pin, forget (`?incorrect=true`) |
| `POST /memories/{id}/profile-proposal`, `GET /profile-proposals`, `POST …/{id}/resolve`, `GET /profile-revisions` | profile refinement |

### SSE protocol (`text/event-stream`, `event:` + one-line JSON `data:`)

```
started  {user_message_id, assistant_message_id, provider, model, is_sample, replayed,
          context{earlier_messages_used,total,trimmed}, profile_outdated, memories_used[{id,statement}]}
delta    {text}                 one per real piece of model output; nothing is invented or re-chunked
done     {assistant_message_id, status:"complete", first_token_ms, duration_ms, correction_hint}
error    {code, assistant_message_id, message, partial_saved}      (terminal; partial text is kept, never "complete")
```
Refusals before streaming starts are normal HTTP errors (403 `consent_required`, 409 `no_profile`/`in_progress`,
429 `model_busy`/`rate_limited`, 503 `chat_provider_unsupported`/`not_configured`/`ai_disabled`, 404 not yours).

Guarantees (all covered by mocked tests; the first two also over real sockets, see below):
- The client message id makes a send idempotent: a repeat of a finished turn replays the saved reply (`replayed:true`);
  a retry of a failed/cancelled/incomplete turn replaces that reply without a second user message.
- A reply is `complete` only if the model finished normally. Failure, empty output, cut-off at the length limit and
  Stop are stored as `failed`/`incomplete`/`cancelled` with their partial text, and are never fed back as history.
- Closing the connection (Stop) saves the partial text as `cancelled` and releases the model slot. A process restart
  cannot leave "running" rows: `streaming` rows not owned by this process are shown as `incomplete`.
- History sent to the model is bounded (`CHAT_CONTEXT_MESSAGES`, `CHAT_CONTEXT_CHARS`) and the UI is told when it was trimmed.
- Timeouts are separate and configurable: first token (`CHAT_FIRST_TOKEN_TIMEOUT_SECONDS`) and total
  (`CHAT_TOTAL_TIMEOUT_SECONDS`). The browser uses a dedicated streaming helper (no 20 s limit), aborts on Stop.
- Logs carry codes, counts and ids, never message text.

## Learning lifecycle

1. **Consent.** `learning_preferences.enabled` (default off) is separate from AI-processing consent. Turning it off stops
   reviews; it does not delete memories. Both are re-checked when the job starts and again just before it writes.
2. **Review (user-triggered, never per message).** "Review what Madhuora learned" starts a background job (202), bounded to
   `LEARNING_REVIEW_MESSAGES` newest complete messages, `LEARNING_REVIEWS_PER_HOUR`, one model job at a time. A failure is
   stored as `conversations.learning_failure_code` and never affects chat.
3. **Validation (`validate_candidates`).** Every candidate needs verbatim quotes (≥ 8 chars) from the *user's* messages;
   statement and quote must share content; `repeated_pattern` needs two different messages; hypotheticals/role-play and
   passing moods are judged on the whole sentence and dropped unless the user said "remember…"; sensitive attributes the
   user did not state are dropped; known/rejected fingerprints are dropped; at most `LEARNING_MAX_CANDIDATES`. Evidence is a
   category (`explicit_statement`, `correction`, `memory_request`, `repeated_pattern`), not a made-up confidence number.
4. **Approval.** Approve / edit-then-approve / reject. A rejected idea keeps only its fingerprint (text and quotes blanked)
   so it does not return. An identical memory → 409 `duplicate`; an overlapping one → 409 `conflict` listing it, and the user
   chooses `replace` (old one becomes `superseded`, linked) or `keep_both`. Nothing is chosen silently.
5. **Use.** Only active memories are retrieved: lexical relevance weighted by evidence type, pinned first, at most
   `CHAT_MEMORY_LIMIT`. (No embeddings are configured, so this is keyword overlap, not semantic search.) The reply shows
   "informed by N approved memories" with their text.
6. **Profile refinement.** Corrections and repeated patterns in a few categories create a *proposal* automatically;
   any memory can be proposed manually. Accept (optionally edited), reject, or defer. Accepting snapshots the previous
   profile into `profile_revisions`, appends one entry to one list section (max 8, validated), and never touches the
   description. Re-running the analysis also snapshots first if accepted refinements exist, so nothing is lost silently.
7. **Deleting.** Forgetting a memory removes its text and open proposals and keeps only a rejected fingerprint; accepted
   profile changes stay (their snapshots are in the history). Deleting a conversation deletes its messages and unreviewed
   candidates; approved memories are kept without their quotes (`source_deleted`) unless the user also chooses to delete them.

## Known limits (stated honestly)

- `qwen3.5:9b` measured ~3.7 tokens/s on the development machine for analysis; expect long waits for the first words
  and slow replies. Measure with `python -m scripts.live_chat_smoke`.
- Candidate quality depends on the local model; the validator removes ungrounded items but cannot judge whether a kept
  item is *useful*. Review is manual by design.
- Several REST calls per action are not one database transaction (see `MIGRATIONS.md`).
- Per-process state (`_streaming`, `_reviewing`, the model gate) assumes one backend worker.
- Rate limits are counted from stored rows (messages / reviews per hour), not a shared limiter.
