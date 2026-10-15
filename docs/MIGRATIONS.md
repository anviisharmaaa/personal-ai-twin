# Migration reconciliation (checked 2026-10-14, development project `eqdlmlayfbehgtoswnhd`)

| Recorded in Supabase history | Local file |
|---|---|
| `20261014074116` `core_schema` | `supabase/migrations/20261014074116_core_schema.sql` |
| `20261014093552` `character` | `supabase/migrations/20261014093552_character.sql` |

- Both migrations were applied once through the Supabase tool, which assigns the version from the apply time. The local
  files were first created with placeholder versions (`...000001`, `...000002`); they were **renamed** to the recorded
  versions so the local folder and the history line up. No migration was re-applied, nothing was reset, and no history
  was edited.
- Live schema was compared with the file by inspection: all 12 `character_profiles`/`ai_usage` columns and the 3 new
  `twins` columns exist with the expected types and nullability, the 6 policies exist for role `authenticated`, RLS is
  enabled on all 6 public tables, and `anon` has no SELECT on any of them. This was an object-level check; the stored
  SQL text was not diffed byte-for-byte (the applied text omitted the file's comments).
- This confirms the policies *exist*. It does not prove isolation between users; see `LIVE_VERIFICATION.md` §4.

## Phase 4 (applied 2026-10-15)

| Recorded in Supabase history | Local file |
|---|---|
| `20261015054824` `conversations_learning` | `supabase/migrations/20261015054824_conversations_learning.sql` |

- Additive only: seven new tables (`conversations`, `messages`, `learning_preferences`, `memory_candidates`, `memories`,
  `profile_proposals`, `profile_revisions`). No existing table, policy or row was touched; nothing was dropped or reset.
- Applied once through the Supabase tool. The local file was renamed to the recorded version (as before) and the
  stored SQL had the file's comments removed.
- Checked after applying: RLS enabled on all seven; the security advisor reports only the existing
  "leaked password protection disabled" warning (needs a paid plan). Policies exist for role `authenticated`;
  `anon` has no grants. `profile_revisions` has select/insert policies only (history cannot be rewritten or deleted
  by the user's token).
- This shows the policies *exist*. Isolation between two real users is still **unverified** until
  `python -m scripts.two_account_check` prints ALL PASSED (it now covers these tables too).
- Constraints worth knowing: unique `(conversation_id, client_message_id)` for user messages (idempotent sends);
  check constraints on status/category/evidence values and text sizes; foreign keys `on delete cascade` from the
  user, `on delete set null` for memory → conversation / candidate links so approved memories survive a deleted chat.
- Not transactional: the API performs several REST calls per action (for example approve = insert memory, then update
  candidate). A crash between two calls can leave a candidate "pending" next to an already-created memory; approving it
  again is refused as a duplicate and the user can reject it. Moving these into Postgres functions is the follow-up if
  that ever matters.
