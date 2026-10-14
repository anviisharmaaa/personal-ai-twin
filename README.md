# Madhuora

Personal AI digital-twin platform. **Status: Stages 1–3 of the roadmap** (foundation, data/auth/storage, brand shell + onboarding + Twin Studio). Chat, memory, voice, scheduling, export and deletion are **not built yet** and are shown as "not available" in the UI.

## Layout
- `frontend/` React + TypeScript + Vite + Tailwind v4, TanStack Query, motion
- `backend/` FastAPI (validates Supabase JWTs, acts on the DB *as the user* so RLS applies)
- `supabase/migrations/` version-controlled SQL (applied to the dev project)

## Run locally
```bash
# backend
cd backend && python -m venv .venv && .venv\Scripts\activate   # (Windows)  | source .venv/bin/activate (mac/linux)
pip install -r requirements-dev.txt
copy ..\.env.example .env      # then fill in values; never commit .env
uvicorn app.main:app --reload  # http://localhost:8000/health

# frontend (new terminal)
cd frontend && npm install
copy .env.example .env.local   # fill VITE_* values
npm run dev                    # http://localhost:5173
```
Supabase dashboard > Authentication > URL Configuration: set Site URL `http://localhost:5173` and add redirect URL `http://localhost:5173/auth/callback`. Email confirmation and SMTP are configured there too.

## Checks
`backend`: `ruff check . && mypy app tests && pytest -q` · `frontend`: `npm run typecheck && npm run lint && npm test && npm run build && npm run e2e`
The e2e suite and `backend/tests` use **mocked** Supabase/API; they do not prove the live services work.

## Notes
- Service-role key is never used in this stage and never goes to the browser.
- Data region: Supabase `ap-south-1` (Mumbai). The external AI provider (NVIDIA free development endpoint now; OpenAI possible later) processes data outside India; the exact provider is disclosed in onboarding and Settings.
- Logo rule: maroon wordmark only on gold plate, gold wordmark only on maroon plate (`frontend/src/lib/brand.ts`).

## Character analysis

The Character tab stores the user's own description (`twins.character_description`, source of truth) and a
separate AI-derived profile (`character_profiles`). A profile is "current" only if it was made from the
description's current `character_version`; editing the text marks it outdated without deleting it, and a
failed analysis never overwrites the last good profile.

- Server-side only; provider keys never reach the browser. Provider boundary: `CharacterAnalyzer` (`app/character.py`);
  implementations and selection in `app/providers.py`.
- **`AI_PROVIDER` is explicit**: `nvidia` (free development endpoint, `NVIDIA_API_KEY` + `NVIDIA_CHARACTER_MODEL`), `openai`
  (`OPENAI_API_KEY` + `OPENAI_CHARACTER_MODEL`, paid, for later), `mock` (fixed sample output, no network, refused in
  production) or empty (AI off). No automatic fallback: if the provider fails, the user sees an honest error and the last
  good profile is kept. Mock results are labelled as samples in the API and UI.
- Consent is **provider-specific** (`2026-10-v3-<provider>`): changing provider requires re-consent, and the disclosure text
  comes from the server so it always names the provider actually in use. The stored profile records its provider, so a
  sample (or another provider's) profile is never reused as a cache hit for a different provider.
- The NVIDIA free endpoint is for testing/evaluation and its terms allow NVIDIA to monitor content and use it to improve
  its AI models. Use fictional descriptions only with it (see `docs/LIVE_VERIFICATION.md`).
- Identical, unchanged descriptions are served from storage (no second model call). One analysis per twin runs at a time
  **per server process** (use a database lock if you ever run several workers). `ANALYSIS_DAILY_LIMIT` and `AI_ENABLED` bound spend,
  but provider-side billing limits are still the real budget guard.
- `ai_usage` stores counts and token numbers only, never content.
- Model output is **grounded before saving** (`app/grounding.py`): typical expressions must be exact text from the description,
  context tendencies need a verbatim evidence quote, short descriptions get a bounded profile, and unsupported sensitive
  attributes are rejected. Failures (`quality_failed`) keep the last good profile. See `docs/EVALUATION.md`.

### Verification status
- Mocked: backend pytest (FakeSupabase + FakeAnalyzer + mocked HTTP for the OpenAI and NVIDIA adapters), Playwright with a mocked API.
- NOT yet verified live: a real NVIDIA call (model availability, `nvext.guided_json` acceptance, latency), a real OpenAI
  call, real RLS isolation for the new tables, quality of interpretations on representative descriptions.

Live steps (model access, smoke test, UI test, leaked-password protection, two-account RLS check): `docs/LIVE_VERIFICATION.md`.
Migration history reconciliation: `docs/MIGRATIONS.md`.
