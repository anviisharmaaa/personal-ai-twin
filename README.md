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
- Data region: Supabase `ap-south-1` (Mumbai). AI provider (OpenAI) will process data outside India when chat ships; this is disclosed during onboarding.
- Logo rule: maroon wordmark only on gold plate, gold wordmark only on maroon plate (`frontend/src/lib/brand.ts`).
