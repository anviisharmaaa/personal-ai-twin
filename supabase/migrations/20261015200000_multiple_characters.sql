-- Let one account own several separately identified characters, keeping exactly one personal self-twin.
--
-- Audit of the live schema (checked 2026-10-15 before writing this):
--   twins_kind_check          CHECK (kind = 'self')                -> only 'self' could ever exist
--   twins_one_per_owner       UNIQUE (owner_id)                    -> a second row of ANY kind was refused
--   RLS twins_select/insert/update/delete all `auth.uid() = owner_id` (already per-row, no change needed)
--   FKs to twins(id): conversations, memories, memory_candidates, profile_proposals, profile_revisions,
--   character_profiles (unique twin_id) -- every one already keyed by twin id, so each character gets its own
--   description (twins.character_description), profile, memories and conversations without further change.
--
-- Additive and data-preserving: existing rows are all kind = 'self' and stay valid. No row is read, moved or deleted.
--
-- REVERT (only valid while no account has more than one twin; delete extra characters first):
--   drop trigger twins_guard on public.twins;
--   drop function public.twins_guard();
--   drop index public.twins_one_self_per_owner;
--   alter table public.twins drop constraint twins_kind_check;
--   alter table public.twins add constraint twins_kind_check check (kind = 'self');
--   create unique index twins_one_per_owner on public.twins (owner_id);

alter table public.twins drop constraint twins_kind_check;
alter table public.twins add constraint twins_kind_check check (kind in ('self', 'character'));

-- One personal self-twin per user (the old rule), but any number of other characters.
create unique index twins_one_self_per_owner on public.twins (owner_id) where kind = 'self';
drop index public.twins_one_per_owner;

create index if not exists twins_owner_created_idx on public.twins (owner_id, created_at);

-- Guard rails the table check constraints cannot express: a character's kind never changes (a character cannot be
-- promoted to a second "self"), and an account is capped so it cannot be filled with rows.
create or replace function public.twins_guard() returns trigger
language plpgsql set search_path = '' as $$
begin
  if tg_op = 'UPDATE' then
    if new.kind is distinct from old.kind or new.owner_id is distinct from old.owner_id then
      raise exception 'a twin cannot change its kind or owner' using errcode = '23514';
    end if;
  elsif (select count(*) from public.twins t where t.owner_id = new.owner_id) >= 25 then
    raise exception 'character limit reached' using errcode = '23514';
  end if;
  return new;
end $$;
revoke execute on function public.twins_guard() from public, anon, authenticated;
create trigger twins_guard before insert or update on public.twins
  for each row execute function public.twins_guard();
