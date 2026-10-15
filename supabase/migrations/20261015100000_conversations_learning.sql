-- Phase 4: persistent conversations, streamed-chat messages and approval-based conversational learning.
-- Additive only: no existing table, policy or row is changed or dropped.
--
-- Knowledge is kept in separate tables on purpose:
--   twins.character_description  the user's own words (never touched by the AI)
--   character_profiles           the AI's validated interpretation of that description
--   messages                     conversation history
--   memory_candidates            proposals extracted from the user's own messages, NOT used by the chat until approved
--   memories                     approved, user-editable, deletable memories (the only persistent conversational memory)
--   profile_proposals/revisions  reviewable changes to the structured profile, with version history

create table if not exists public.conversations (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users (id) on delete cascade,
  twin_id uuid not null references public.twins (id) on delete cascade,
  title text not null default 'New conversation' check (char_length(title) between 1 and 120),
  created_at timestamptz not null default now(),
  last_activity_at timestamptz not null default now(),
  archived_at timestamptz,
  learning_reviewed_at timestamptz,
  learning_failure_code text   -- last failed 'review what Madhuora learned' attempt, so it can be retried later
);
create index if not exists conversations_owner_activity_idx on public.conversations (owner_id, last_activity_at desc);

create table if not exists public.messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.conversations (id) on delete cascade,
  owner_id uuid not null references auth.users (id) on delete cascade,
  role text not null check (role in ('user', 'assistant')),
  content text not null default '' check (char_length(content) <= 20000),
  -- complete: finished. streaming: being generated right now. incomplete: interrupted (partial text kept).
  -- cancelled: the user stopped it. failed: the provider failed (partial text, if any, is kept but never "complete").
  status text not null check (status in ('complete', 'streaming', 'incomplete', 'cancelled', 'failed')),
  -- User messages carry the browser-generated idempotency key; assistant messages point at the user message they answer.
  client_message_id text check (client_message_id is null or char_length(client_message_id) <= 64),
  reply_to uuid references public.messages (id) on delete set null,
  provider text,
  model text,
  first_token_ms integer,
  duration_ms integer,
  failure_code text,
  used_memory_ids uuid[] not null default '{}',
  created_at timestamptz not null default now()
);
create index if not exists messages_conversation_created_idx on public.messages (conversation_id, created_at);
-- A retried user message (same key) can never create a second user row.
create unique index if not exists messages_user_idempotency_idx
  on public.messages (conversation_id, client_message_id) where role = 'user' and client_message_id is not null;

create table if not exists public.learning_preferences (
  owner_id uuid primary key references auth.users (id) on delete cascade,
  enabled boolean not null default false,
  enabled_at timestamptz,
  disabled_at timestamptz,
  disclosure_version text,
  updated_at timestamptz not null default now()
);

create table if not exists public.memory_candidates (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users (id) on delete cascade,
  twin_id uuid not null references public.twins (id) on delete cascade,
  conversation_id uuid references public.conversations (id) on delete set null,
  statement text not null default '' check (char_length(statement) <= 400),
  category text not null check (category in
    ('fact', 'preference', 'boundary', 'communication_style', 'trait', 'context_behaviour', 'correction')),
  scope text not null default '' check (char_length(scope) <= 160),
  evidence_type text not null check (evidence_type in
    ('explicit_statement', 'correction', 'memory_request', 'repeated_pattern')),
  -- [{message_id, quote}] : verbatim quotes from the USER'S OWN messages. Never assistant text.
  supporting jsonb not null default '[]',
  status text not null default 'pending' check (status in ('pending', 'approved', 'rejected', 'superseded')),
  fingerprint text not null,
  rejected_reason text,
  created_at timestamptz not null default now(),
  reviewed_at timestamptz
);
create index if not exists memory_candidates_owner_status_idx on public.memory_candidates (owner_id, status, created_at desc);
create index if not exists memory_candidates_owner_fp_idx on public.memory_candidates (owner_id, fingerprint);

create table if not exists public.memories (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users (id) on delete cascade,
  twin_id uuid not null references public.twins (id) on delete cascade,
  candidate_id uuid references public.memory_candidates (id) on delete set null,
  conversation_id uuid references public.conversations (id) on delete set null,
  statement text not null check (char_length(statement) between 1 and 400),
  category text not null check (category in
    ('fact', 'preference', 'boundary', 'communication_style', 'trait', 'context_behaviour', 'correction')),
  scope text not null default '' check (char_length(scope) <= 160),
  evidence_type text not null check (evidence_type in
    ('explicit_statement', 'correction', 'memory_request', 'repeated_pattern')),
  supporting jsonb not null default '[]',
  source_deleted boolean not null default false,
  edited boolean not null default false,
  pinned boolean not null default false,
  status text not null default 'active' check (status in ('active', 'superseded')),
  superseded_by uuid references public.memories (id) on delete set null,
  fingerprint text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists memories_owner_status_idx on public.memories (owner_id, status, created_at desc);

create table if not exists public.profile_proposals (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users (id) on delete cascade,
  twin_id uuid not null references public.twins (id) on delete cascade,
  memory_id uuid references public.memories (id) on delete set null,
  section text not null,
  current_text text,
  proposed_text text not null check (char_length(proposed_text) between 1 and 320),
  kind text not null check (kind in ('correction', 'new_evidence', 'contextual_exception')),
  evidence jsonb not null default '[]',
  status text not null default 'pending' check (status in ('pending', 'accepted', 'rejected', 'deferred')),
  created_at timestamptz not null default now(),
  resolved_at timestamptz
);
create index if not exists profile_proposals_owner_status_idx on public.profile_proposals (owner_id, status, created_at desc);

create table if not exists public.profile_revisions (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users (id) on delete cascade,
  twin_id uuid not null references public.twins (id) on delete cascade,
  profile jsonb not null,            -- the profile as it was BEFORE the change
  reason text not null check (reason in ('proposal_accepted', 'regenerated')),
  proposal_id uuid references public.profile_proposals (id) on delete set null,
  created_at timestamptz not null default now()
);
create index if not exists profile_revisions_owner_idx on public.profile_revisions (owner_id, created_at desc);

alter table public.conversations enable row level security;
alter table public.messages enable row level security;
alter table public.learning_preferences enable row level security;
alter table public.memory_candidates enable row level security;
alter table public.memories enable row level security;
alter table public.profile_proposals enable row level security;
alter table public.profile_revisions enable row level security;

revoke all on public.conversations, public.messages, public.learning_preferences, public.memory_candidates,
  public.memories, public.profile_proposals, public.profile_revisions from anon;

-- conversations: own rows only, and only on the owner's own twin.
create policy "conversations_select_own" on public.conversations
  for select to authenticated using (owner_id = (select auth.uid()));
create policy "conversations_insert_own" on public.conversations
  for insert to authenticated with check (
    owner_id = (select auth.uid())
    and exists (select 1 from public.twins t where t.id = twin_id and t.owner_id = (select auth.uid())));
create policy "conversations_update_own" on public.conversations
  for update to authenticated using (owner_id = (select auth.uid())) with check (owner_id = (select auth.uid()));
create policy "conversations_delete_own" on public.conversations
  for delete to authenticated using (owner_id = (select auth.uid()));

-- messages: own rows only, and only inside the owner's own conversation (a guessed conversation id is useless).
create policy "messages_select_own" on public.messages
  for select to authenticated using (owner_id = (select auth.uid()));
create policy "messages_insert_own" on public.messages
  for insert to authenticated with check (
    owner_id = (select auth.uid())
    and exists (select 1 from public.conversations c
                where c.id = conversation_id and c.owner_id = (select auth.uid())));
create policy "messages_update_own" on public.messages
  for update to authenticated using (owner_id = (select auth.uid())) with check (owner_id = (select auth.uid()));
create policy "messages_delete_own" on public.messages
  for delete to authenticated using (owner_id = (select auth.uid()));

create policy "learning_preferences_select_own" on public.learning_preferences
  for select to authenticated using (owner_id = (select auth.uid()));
create policy "learning_preferences_insert_own" on public.learning_preferences
  for insert to authenticated with check (owner_id = (select auth.uid()));
create policy "learning_preferences_update_own" on public.learning_preferences
  for update to authenticated using (owner_id = (select auth.uid())) with check (owner_id = (select auth.uid()));

-- candidates / memories / proposals / revisions: own rows, own twin.
create policy "memory_candidates_select_own" on public.memory_candidates
  for select to authenticated using (owner_id = (select auth.uid()));
create policy "memory_candidates_insert_own" on public.memory_candidates
  for insert to authenticated with check (
    owner_id = (select auth.uid())
    and exists (select 1 from public.twins t where t.id = twin_id and t.owner_id = (select auth.uid())));
create policy "memory_candidates_update_own" on public.memory_candidates
  for update to authenticated using (owner_id = (select auth.uid())) with check (owner_id = (select auth.uid()));
create policy "memory_candidates_delete_own" on public.memory_candidates
  for delete to authenticated using (owner_id = (select auth.uid()));

create policy "memories_select_own" on public.memories
  for select to authenticated using (owner_id = (select auth.uid()));
create policy "memories_insert_own" on public.memories
  for insert to authenticated with check (
    owner_id = (select auth.uid())
    and exists (select 1 from public.twins t where t.id = twin_id and t.owner_id = (select auth.uid())));
create policy "memories_update_own" on public.memories
  for update to authenticated using (owner_id = (select auth.uid())) with check (owner_id = (select auth.uid()));
create policy "memories_delete_own" on public.memories
  for delete to authenticated using (owner_id = (select auth.uid()));

create policy "profile_proposals_select_own" on public.profile_proposals
  for select to authenticated using (owner_id = (select auth.uid()));
create policy "profile_proposals_insert_own" on public.profile_proposals
  for insert to authenticated with check (
    owner_id = (select auth.uid())
    and exists (select 1 from public.twins t where t.id = twin_id and t.owner_id = (select auth.uid())));
create policy "profile_proposals_update_own" on public.profile_proposals
  for update to authenticated using (owner_id = (select auth.uid())) with check (owner_id = (select auth.uid()));
create policy "profile_proposals_delete_own" on public.profile_proposals
  for delete to authenticated using (owner_id = (select auth.uid()));

-- Revisions are history: the user can read and add their own, not rewrite or delete them.
create policy "profile_revisions_select_own" on public.profile_revisions
  for select to authenticated using (owner_id = (select auth.uid()));
create policy "profile_revisions_insert_own" on public.profile_revisions
  for insert to authenticated with check (
    owner_id = (select auth.uid())
    and exists (select 1 from public.twins t where t.id = twin_id and t.owner_id = (select auth.uid())));
