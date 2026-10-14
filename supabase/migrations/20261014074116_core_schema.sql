-- Madhuora core schema (Stage 2). RLS is enabled on every table (Decision 4).

create or replace function public.set_updated_at() returns trigger
language plpgsql set search_path = '' as $$
begin new.updated_at = now(); return new; end $$;

create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text check (char_length(display_name) <= 80),
  timezone text not null default 'UTC',
  deletion_status text not null default 'active'
    check (deletion_status in ('active','pending','completed')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create trigger profiles_updated before update on public.profiles
  for each row execute function public.set_updated_at();

create function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  insert into public.profiles (id) values (new.id) on conflict do nothing;
  return new;
end $$;
revoke execute on function public.handle_new_user() from public, anon, authenticated;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function public.handle_new_user();

create table public.twins (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  kind text not null default 'self' check (kind in ('self')),
  name text not null check (char_length(name) between 1 and 80),
  about text check (char_length(about) <= 2000),
  personality jsonb not null default '{}'::jsonb,
  communication jsonb not null default '{}'::jsonb,
  appearance jsonb not null default '{}'::jsonb,
  portrait_path text,
  portrait_permission_confirmed boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
-- V1: one self-twin per account.
create unique index twins_one_per_owner on public.twins (owner_id);
create trigger twins_updated before update on public.twins
  for each row execute function public.set_updated_at();

create table public.onboarding_steps (
  user_id uuid not null references auth.users(id) on delete cascade,
  step text not null check (step in
    ('welcome','identity','personality','memory_import','memory_review','first_chat','refinements')),
  completed_at timestamptz not null default now(),
  primary key (user_id, step)
);

create table public.consents (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  kind text not null check (kind in ('ai_processing')),
  version text not null,
  granted_at timestamptz not null default now(),
  withdrawn_at timestamptz
);
create index consents_user_idx on public.consents (user_id, kind);

alter table public.profiles enable row level security;
alter table public.twins enable row level security;
alter table public.onboarding_steps enable row level security;
alter table public.consents enable row level security;

revoke all on public.profiles, public.twins, public.onboarding_steps, public.consents from anon;

create policy profiles_select on public.profiles for select to authenticated
  using ((select auth.uid()) = id);
create policy profiles_update on public.profiles for update to authenticated
  using ((select auth.uid()) = id) with check ((select auth.uid()) = id);

create policy twins_select on public.twins for select to authenticated
  using ((select auth.uid()) = owner_id);
create policy twins_insert on public.twins for insert to authenticated
  with check ((select auth.uid()) = owner_id);
create policy twins_update on public.twins for update to authenticated
  using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);
create policy twins_delete on public.twins for delete to authenticated
  using ((select auth.uid()) = owner_id);

create policy steps_select on public.onboarding_steps for select to authenticated
  using ((select auth.uid()) = user_id);
create policy steps_insert on public.onboarding_steps for insert to authenticated
  with check ((select auth.uid()) = user_id);
create policy steps_delete on public.onboarding_steps for delete to authenticated
  using ((select auth.uid()) = user_id);

create policy consents_select on public.consents for select to authenticated
  using ((select auth.uid()) = user_id);
create policy consents_insert on public.consents for insert to authenticated
  with check ((select auth.uid()) = user_id);
create policy consents_update on public.consents for update to authenticated
  using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);

-- Private portrait storage: objects live under "<user_id>/..." only.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('portraits', 'portraits', false, 5242880, array['image/jpeg','image/png','image/webp'])
on conflict (id) do nothing;

create policy portraits_select on storage.objects for select to authenticated
  using (bucket_id = 'portraits' and (storage.foldername(name))[1] = (select auth.uid())::text);
create policy portraits_insert on storage.objects for insert to authenticated
  with check (bucket_id = 'portraits' and (storage.foldername(name))[1] = (select auth.uid())::text);
create policy portraits_update on storage.objects for update to authenticated
  using (bucket_id = 'portraits' and (storage.foldername(name))[1] = (select auth.uid())::text);
create policy portraits_delete on storage.objects for delete to authenticated
  using (bucket_id = 'portraits' and (storage.foldername(name))[1] = (select auth.uid())::text);
