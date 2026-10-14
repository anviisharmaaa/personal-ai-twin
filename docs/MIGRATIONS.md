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
