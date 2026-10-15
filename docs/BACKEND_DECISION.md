# Backend decision: keep Supabase (evidence, 2026-10-15)

## What the real development project showed (read-only metadata queries; no description or profile text was read)

Project `personal-ai-twin` (ap-south-1), migrations `core_schema` and `character` applied, RLS enabled on all six
public tables, security advisor: one WARN only (leaked-password protection disabled; needs Supabase Pro).

| Observation (UTC) | Meaning |
|---|---|
| NVIDIA consent withdrawn 04:05:48, Ollama consent granted 04:05:54, still active | Consent is saved and persists in Supabase. The "consent needed" warning was the by-design re-consent after switching provider. |
| `qwen3.5:9b` error recorded 04:09:48, about 303 s after the description was saved | Matches the old 300 s Ollama timeout, not a Supabase fault. |
| `qwen3.5:9b` success 04:46:31: 296,944 ms, 2,946 prompt tokens, 1,100 output tokens (about 3.7 tokens/s) | A real Ollama analysis was validated and persisted (profile row: `ollama:qwen3.5:9b`, description version 4 = twin version 4, failure cleared). The model ran only just inside the old limit. Speed, not storage, is the bottleneck. |

Every observed defect belongs elsewhere: re-consent (backend consent versions), timeouts (Ollama speed + a synchronous
HTTP request), a stale failure message (frontend state), the dynamic-import error (Vite dev server; the production
build is fine and the error is not reproducible from a clean build).

## Options compared

| | Keep Supabase | FastAPI + SQLite (dev) with a Supabase adapter | Self-hosted Postgres + auth layer |
|---|---|---|---|
| Fixes any observed defect | n/a - none were caused by it | No | No |
| Auth | Supabase Auth (verified, hosted) | Needs a new auth layer for dev: a second path that could diverge from production | Must build/operate auth (sessions, resets, email) |
| Security | RLS enforced in the database | No RLS; ownership only in code | RLS possible, but you operate the server |
| Migrations / portability | SQL migrations in repo; standard Postgres | Two schemas to keep equal | Same Postgres, you run backups |
| Mobile / multi-user later | Ready | Not suitable | Possible with work |
| Cost/complexity now | None | High: second storage path and test matrix | High: ops burden |

**Decision: keep Supabase.** No migration, nothing destructive, no change to the existing project. Revisit only if a
reproduced, Supabase-caused blocker appears.

## Still unverified (needs you)
Two-account RLS test through the real API/PostgREST (`python -m scripts.two_account_check`), private portrait storage
via a real upload, account deletion, leaked-password protection (paid plan).
