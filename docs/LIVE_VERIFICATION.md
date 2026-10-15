# Live verification runbook (development project only)

Everything below is **LIVE** and separate from the mocked test suites. Do it in this order.

## 0. Sync and configure (once)
```powershell
cd C:\Users\anvii\OneDrive\Desktop\madhuora\webapp
git fetch origin
git checkout character-workspace
git pull
```
Open `backend\.env` in your editor (it is git-ignored and never leaves your machine). The provider is chosen
**explicitly** with `AI_PROVIDER`; nothing is inferred from which keys exist, and there is no fallback to another
provider. Type keys directly into the file; never paste them into chat or terminal output.

**Free development provider: NVIDIA NIM** (no OpenAI credits needed):
```
AI_PROVIDER=nvidia
NVIDIA_API_KEY=<your key from build.nvidia.com, only in this file>
NVIDIA_CHARACTER_MODEL=nvidia/nemotron-3-super-120b-a12b
```
Get a key: sign in at <https://build.nvidia.com>, open the model page and use "Get API Key". Keys start `nvapi-`.
The request disables Nemotron's reasoning (`chat_template_kwargs.enable_thinking=false`) and allows 4096 output tokens
(`NVIDIA_MAX_OUTPUT_TOKENS`, bounded 512 to 8192). If a run still shows `reasoning_tokens` above 0 the smoke test prints a warning.
Optional: `NVIDIA_JSON_MODE=prompt` if the endpoint rejects `nvext.guided_json` (the smoke test will print NVIDIA's reason).

**Sample mode (no network, no key, no cost):** `AI_PROVIDER=mock`. Results are fixed examples and are labelled
"Sample output, not an AI reading" in the app. It is refused when `APP_ENV=production`.

**Later, OpenAI (paid):** `AI_PROVIDER=openai`, `OPENAI_API_KEY`, `OPENAI_CHARACTER_MODEL`. Nothing else changes.
(The retired `OPENAI_CHAT_MODEL` name is still ignored; `/ready` warns if only it is present.)

Restart the backend. `http://localhost:8000/ready` should show `"ai_provider": "nvidia"` and `"ai": true`. It reports
names and true/false only, never values.

**Before using NVIDIA at all, read NVIDIA's current API Trial Terms yourself.** When I read them they said: the service is
for trial/"internal testing and evaluation"; NVIDIA may monitor content; submitted and generated content may be used to
improve NVIDIA products and AI models; uploading personal information about identifiable people is not permitted unless
expressly allowed; and the servers are not appropriate for personal, health or payment data. Terms can change. Until you
are comfortable with them, use **only fictional descriptions** with this provider. Never use real people's details.

## 1. Live smoke test (do this BEFORE trying the UI)
```powershell
cd backend
& $HOME\venvs\madhuora\Scripts\Activate.ps1
python -m scripts.live_character_smoke            # access check, ONE analysis, error handling
python -m scripts.live_character_smoke --eval     # then, if that passed: 8 more calls (fictional descriptions)
```
It prints authentication/model availability, schema validity, latency and token usage, and writes every returned profile to
`backend\scripts\out\` (git-ignored). Paste the console output back to me; it contains no secrets. Do not paste the .env.

## 2. Only after step 1 succeeds: test the Character workspace in the browser (LIVE, fictional text only)
Start both servers (two terminals, venv active in the first):
```powershell
cd backend ; uvicorn app.main:app --reload --port 8000
cd frontend ; npm run dev            # http://localhost:5173 (needs frontend\.env from .env.example)
```
`http://localhost:8000/ready` must show `"ai_provider": "nvidia"` and `"ai": true`. Use only the fictional text below
(or your own invented text). Tick each line only after you have actually seen it.

Fictional test description (copy exactly; it has several contexts):
> Meera remembers everyone's birthdays. She teases her closest friends constantly but goes quiet and careful around
> people she has just met. She never says 'I love you' out loud; she shows it by turning up with food. With her
> grandfather she is soft-spoken and patient. At work she is direct and a bit blunt in meetings, but afterwards she
> checks in with anyone she may have stung. She is loud and silly at family weddings.

| # | Check | Expected |
|---|-------|----------|
| 1 | Settings: before consenting, open Studio, Character, try "Understand this character" | Disabled/blocked with an explanation; no request leaves for NVIDIA (DevTools, Network: no `/character/analyze` call). |
| 2 | Settings: read the disclosure and accept | Text names **NVIDIA** and the trial/fictional-only warning; consent recorded. |
| 3 | Studio, Character: paste the description, Save, then Ctrl+F5 | Exact original text is back; "Development AI provider" warning visible. |
| 4 | Click "Understand this character" | A clear loading state (button busy, status announced), then status "Up to date". |
| 5 | Read the profile | Each situation (grandfather, work meetings, weddings, friends, strangers) appears **once**, under "Depending on the situation", with a "From your description: ..." quote; no section repeats the same fact. Typical expressions, if any, are exact text from your description. |
| 6 | Click again with no edit | Says nothing changed; Network shows no new `/analyze` model call. |
| 7 | Edit one sentence, Save | Profile labelled as made from an earlier version ("Out of date"); old profile still shown. |
| 8 | Click "Update the interpretation" | Loading, then "Up to date" with the new text reflected. |
| 9 | Failure keeps the last profile: stop the backend, set `NVIDIA_API_KEY=invalid` in `backend\.env` (do not paste a real key anywhere), restart, edit the text, Save, analyse | A plain error message (not a crash), status stays "Out of date", **the previous profile is still displayed**, description intact. Then restore your real key and restart. |
| 10 | Settings: withdraw consent | Analysis disabled with an explanation. Agree again to re-enable. |
| 11 | Two tabs: edit and save in both | Second save warns the description changed elsewhere. |
| 12 | Layout: DevTools device toolbar at 375 px and 1280 px | No horizontal scroll; buttons reachable; text readable. |
| 13 | Theme: toggle light and dark (and the OS setting) | Every state in 4, 7, 9 readable in both; no invisible text. |
| 14 | Keyboard and a11y: Tab through the page; run Lighthouse (Accessibility) or the axe DevTools extension on the Character page | Visible focus on every control; status messages announced; no serious/critical issues. |

What is NOT covered here: the mocked suites (`pytest`, `npm run e2e`) exercise these same states against a **fake** API and
fake analysis; they do not prove the NVIDIA path works in your browser. Only this table does. Rows 5 and 9 are the
ones that prove the displayed profile is the validated one and that a failure does not overwrite it. Write down any row
that fails with what you saw; do not skip it.

## 3. Leaked-password protection
Supabase docs state it is available on the **Pro plan and above**. Dashboard: Authentication → Sign In / Providers →
Email → turn on "Prevent use of leaked passwords". If the option is locked, the project is on the Free plan; until you
upgrade, raise the minimum password length (8+, 12 recommended) and require upper/lower/digit/symbol on that same page,
and treat the advisor warning as an accepted risk.

## 4. Live RLS isolation (stays UNVERIFIED until this passes)
Create two separate dev accounts (A and B). Complete onboarding as A. Then:
```powershell
python -m scripts.rls_two_user_check
```
Passwords are typed at a hidden prompt. The script never deletes A's data. Send me the PASS/FAIL lines.

## 5. Local provider (Ollama) — real local inference

Nothing here has been run by Claude: the cloud workspace cannot reach your Ollama. Mocked tests only prove the adapter logic.

1. Install Ollama for Windows from ollama.com, then check hardware (safe, read-only), in PowerShell:
   `Get-CimInstance Win32_ComputerSystem | Select TotalPhysicalMemory; Get-CimInstance Win32_VideoController | Select Name,AdapterRAM; Get-PSDrive C | Select Free`
2. Choose a model by RAM/VRAM and verify its name at ollama.com/library. Approximate download sizes: `qwen3.5:4b` 3.3 GB, `qwen3.5:9b` 6.6 GB. Pull only after you approve the size: `ollama pull <model>`; confirm with `ollama list`.
3. Run the server with a larger context: `$env:OLLAMA_CONTEXT_LENGTH=16384; ollama serve`.
4. In `backend/.env`: `AI_PROVIDER=ollama`, `OLLAMA_CHARACTER_MODEL=<installed name>` (no key needed).
5. First, confirm what is really running (read-only, no secrets): `python -m scripts.check_local` — it compares the provider your `.env` selects with what the RUNNING backend reports at `/ready`, and checks Ollama and the installed model. Restart the backend after any `.env` change.
6. Smoke test: `python -m scripts.live_character_smoke` (fictional sample, error test, then optionally `--eval`).
   Your own text, locally only: `python -m scripts.live_character_smoke --text-file mine.txt` (output in git-ignored `scripts/out/`).
7. Browser checklist = section 2, but with the Ollama notice (local processing, Supabase still stores data) and these descriptions: one short, one detailed, one with contrasting behaviours. Also stop Ollama and confirm the "local model unavailable" error keeps the previous profile, and switch provider to confirm consent re-review.
8. Unverified until you run it: `/v1` acceptance of `response_format` json_schema and `reasoning_effort` for your model (if rejected, set `OLLAMA_JSON_MODE=prompt`), speed, and profile quality.

### 5a. If an Ollama analysis fails ("empty / not valid JSON / wrong structure / didn't pass checks")

1. Backend log line (no text, no keys): `analysis_failed code=<code> provider=ollama detail=<positions, field paths, counts>`.
   Codes: `local_unavailable`, `local_model_missing`, `timeout`, `truncated`, `empty_response`, `not_json`,
   `schema_invalid`, `quality_failed` (grounding rule named in `detail`), `context_too_small`, `consent_required`.
2. `python -m scripts.ollama_probe` tries the four request shapes against YOUR model with the fictional text only and
   says which stage rejects each. Set `OLLAMA_JSON_MODE` / `OLLAMA_REASONING_EFFORT` to the first working shape.
3. "Consent needed" after switching provider is expected: an agreement is tied to the provider (`...-nvidia` does not
   cover `...-ollama`). Agree again in Settings; a stale failure is hidden until you do.

### 5b. Speed and where the model runs (synthetic text only)

Evidence so far (from the development database's usage log): one successful `qwen3.5:9b` analysis took 297 s for
about 1,100 output tokens, roughly 3.7 tokens/s, which is typical of CPU or partial-GPU execution.

- `python -m scripts.ollama_bench` - model load time, then short / rich / long synthetic descriptions, tokens per
  second, which pipeline stage accepted each, and from Ollama's `/api/ps` how much of the model is in GPU memory.
- `python -m scripts.ollama_bench --model qwen3.5:4b` compares an INSTALLED smaller model. It never downloads. If you want
  to compare, run `ollama pull qwen3.5:4b` yourself (3.3 GB) after approving the size; the 9B stays configured until you
  change `OLLAMA_CHARACTER_MODEL`.
- Analysis is now a background job: the request returns at once (202) and the page shows the server's real running
  state with real elapsed time; `OLLAMA_TIMEOUT_SECONDS` (default 600) bounds the model call only. The job lives in the
  server process: restarting the backend mid-analysis drops it (the page then returns to idle with the previous profile).

## 6. Two-account isolation (live; stays UNVERIFIED until it prints ALL PASSED)

Create two throw-away development accounts, confirm both emails, then in PowerShell (values are never printed):
`$env:MADHUORA_TEST_A_EMAIL="..."; $env:MADHUORA_TEST_A_PASSWORD="..."; $env:MADHUORA_TEST_B_EMAIL="..."; $env:MADHUORA_TEST_B_PASSWORD="..."`
then `python -m scripts.two_account_check` (backend running). Portrait privacy needs a real upload: the signed URL must
work, and the bare storage path without a token must not.

## 7. Conversations, streaming and learning (Phase 4) — LIVE steps, none of which has been run yet

Prerequisites: `AI_PROVIDER=ollama`, `OLLAMA_CHARACTER_MODEL=qwen3.5:9b` in `backend/.env`; Ollama running; the Phase 4
migration is already applied to the development project (`docs/MIGRATIONS.md`). Pull the branch first
(`cd C:\Users\anvii\OneDrive\Desktop\madhuora\webapp` then `git pull`).

**7a. Model-level check (no database, synthetic text only)**
`python -m scripts.live_chat_smoke` - three streamed turns (time to first token, total time, tokens/s, number of separate
stream pieces, Hindi/emoji intact, no hidden reasoning leaked) and one extraction on a synthetic conversation, showing
what the model proposed and what the validator kept or dropped. It exits non-zero on a failed check; read the KEPT lines
yourself, the script cannot judge usefulness. Output also goes to `scripts/out/live_chat_smoke.json`.

**7b. Real browser, real backend (use a throw-away account and invented text)**
1. Start backend and frontend as usual; sign in; make sure the Character interpretation exists (analysis finished).
2. Conversations → send a short message. Expect: a spinner labelled "Waiting for the first words" only until the first
   piece, then text growing word by word; Stop mid-reply keeps the partial text marked "Stopped"; reload keeps history.
3. Stop the backend while a reply streams (or close Ollama): the reply must show as interrupted, never as complete, and a
   restart must not leave anything "running".
4. Memories → turn learning on (read the explanation). In a conversation say a few clear things about yourself and one
   correction, then press "Review what Madhuora learned". Wait (minutes on a slow model). Expect suggestions, each with
   your own quote; nothing under "Remembered" until you approve. Approve one, reject one, edit one.
5. Send a related message: the reply should show "Informed by N approved memories". Forget the memory: it must stop appearing.
6. Delete the conversation with and without "also delete the memories" and check the result matches the dialog text.
7. Accept a profile suggestion; History must show the earlier version; the description in Twin Studio must be unchanged.

**7c. Two accounts and the new tables**
`python -m scripts.two_account_check` (see §6) now also covers conversations, messages, candidates, memories, proposals
and revisions (reads, spoofed inserts, takeovers, deletes, anonymous access). Isolation stays **UNVERIFIED** until it
prints ALL PASSED.

**7d. What to report back**: the `live_chat_smoke` timings and KEPT/dropped lists, whether step 7b matched each
expectation (note any that did not), and the `two_account_check` result.

Status today: mocked (backend, vitest, Playwright) and real-socket-with-stub-model checks pass; every item above is unverified.

## 8. Multiple characters and real chat (LIVE; stays UNVERIFIED until you run it)

1. `git pull` on `character-workspace` (the repo now has a `.gitattributes` that normalises line endings; if the pull is
   blocked by line-ending-only changes, run `git checkout -- .` after checking `git diff` shows nothing you wrote).
2. Apply `supabase/migrations/20261015200000_multiple_characters.sql` to the DEVELOPMENT project (SQL editor), restart the backend.
3. Set `MADHUORA_TEST_A_EMAIL` / `MADHUORA_TEST_A_PASSWORD` (throw-away dev account that has granted AI consent and
   has a twin), make sure Ollama is running with your model, then: `python -m scripts.live_multi_character_check`.
   It creates two invented characters, streams a real reply from each, checks incremental tokens, saved status,
   reload, a second conversation with the same character, and that lists never mix. It prints both replies; you judge
   whether each sounds like its own character. Exit code 0 = all checks passed.
4. In the browser: Twin Studio -> "+ New character" -> Conversations -> choose the character -> send a message -> reload.
