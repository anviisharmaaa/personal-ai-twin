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

## 2. Only after step 1 succeeds: test the Character workspace
1. Settings: read the provider disclosure (it must name NVIDIA, not OpenAI) and accept. The consent is tied to the
   provider, so switching `AI_PROVIDER` later asks you to agree again.
2. Studio → Character: write a few **fictional** sentences (you will see a "Development AI provider" warning). Save description. Hard-refresh (Ctrl+F5): the text must still be there.
3. Click "Understand this character": check you get an interpretation and the status reads "Up to date".
4. Edit the text: the interpretation must be flagged as made from an earlier version. Click "Update the interpretation".
5. Click it again without editing: it should say nothing has changed (no new model call).
6. Settings → Withdraw consent: the analysis button must be disabled with an explanation. Agree again to re-enable.
7. Open two tabs, edit in both, save in both: the second save must warn that the description changed elsewhere.

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
