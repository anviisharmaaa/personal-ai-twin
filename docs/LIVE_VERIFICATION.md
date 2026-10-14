# Live verification runbook (development project only)

Everything below is **LIVE** and separate from the mocked test suites. Do it in this order.

## 0. Sync and configure (once)
```powershell
cd C:\Users\anvii\OneDrive\Desktop\madhuora\webapp
git fetch origin
git checkout character-workspace
git pull
```
Open `backend\.env` in your editor (it is git-ignored and never leaves your machine) and make sure it contains
these lines. Type the key directly into the file; do not paste it into chat or any terminal output:
```
OPENAI_API_KEY=<your key, only in this file>
OPENAI_CHARACTER_MODEL=gpt-6-luna
```
If you previously added `OPENAI_CHAT_MODEL`, rename it. The old name is ignored on purpose, and `/ready` will warn if
only the old name is present. Restart the backend afterwards. `http://localhost:8000/ready` should show
`"openai": true`. It reports true/false only, never values.

## 1. Live smoke test (do this BEFORE trying the UI)
```powershell
cd backend
& $HOME\venvs\madhuora\Scripts\Activate.ps1
python -m scripts.live_character_smoke            # access check, ONE analysis, error handling
python -m scripts.live_character_smoke --eval     # then, if that passed: 8 more calls (fictional descriptions)
```
It prints schema validity, latency, token usage and estimated cost, and writes every returned profile to
`backend\scripts\out\` (git-ignored). Paste the console output back to me; it contains no secrets. Do not paste the .env.

## 2. Only after step 1 succeeds: test the Character workspace
1. Settings: accept AI processing (the wording changed, so v1 consent no longer counts).
2. Studio → Character: write a few sentences. Save description. Hard-refresh (Ctrl+F5): the text must still be there.
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
