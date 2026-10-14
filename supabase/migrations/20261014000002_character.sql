-- Character workspace: free-form description (source of truth) + AI-derived profile (interpretation).
-- Additive only: no existing column, row or policy is dropped or rewritten.

-- 1. The user's own words live on the twin. `character_version` increments whenever the text changes,
--    so every analysis can be tied to the exact description it read.
alter table public.twins
  add column if not exists character_description text not null default ''
    check (char_length(character_description) <= 8000),
  add column if not exists character_version integer not null default 0
    check (character_version >= 0),
  add column if not exists character_updated_at timestamptz;

-- 2. The derived profile is kept separate from the description. One row per twin.
--    A failed analysis only touches the last_failure_* columns, never `profile`.
create table if not exists public.character_profiles (
  id uuid primary key default gen_random_uuid(),
  twin_id uuid not null unique references public.twins (id) on delete cascade,
  owner_id uuid not null references auth.users (id) on delete cascade,
  profile jsonb,
  description_version integer,
  description_sha256 text,
  schema_version integer,
  model text,
  generated_at timestamptz,
  last_failure_code text,
  last_failure_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists character_profiles_owner_idx on public.character_profiles (owner_id);

-- 3. Usage ledger for rate limits and budget tracking. Counts and token numbers only:
--    never the description, the profile, or any prompt text.
create table if not exists public.ai_usage (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users (id) on delete cascade,
  kind text not null check (kind in ('character_analysis')),
  status text not null check (status in ('ok', 'error')),
  model text,
  input_tokens integer,
  output_tokens integer,
  latency_ms integer,
  created_at timestamptz not null default now()
);
create index if not exists ai_usage_owner_created_idx on public.ai_usage (owner_id, created_at desc);

alter table public.character_profiles enable row level security;
alter table public.ai_usage enable row level security;

revoke all on public.character_profiles from anon;
revoke all on public.ai_usage from anon;

create policy "character_profiles_select_own" on public.character_profiles
  for select to authenticated using (owner_id = (select auth.uid()));
create policy "character_profiles_insert_own" on public.character_profiles
  for insert to authenticated
  with check (
    owner_id = (select auth.uid())
    and exists (select 1 from public.twins t where t.id = twin_id and t.owner_id = (select auth.uid()))
  );
create policy "character_profiles_update_own" on public.character_profiles
  for update to authenticated
  using (owner_id = (select auth.uid()))
  with check (owner_id = (select auth.uid()));
create policy "character_profiles_delete_own" on public.character_profiles
  for delete to authenticated using (owner_id = (select auth.uid()));

-- Usage rows are append-only for the user: they can read and add their own, not edit or delete.
create policy "ai_usage_select_own" on public.ai_usage
  for select to authenticated using (owner_id = (select auth.uid()));
create policy "ai_usage_insert_own" on public.ai_usage
  for insert to authenticated with check (owner_id = (select auth.uid()));
