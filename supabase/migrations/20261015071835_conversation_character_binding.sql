-- Bind every conversation to exactly one character, in the database (not only in the API).
--
-- Findings that motivate this: conversations.twin_id referenced twins(id) but (1) nothing tied the conversation's owner
-- to the twin's owner except the INSERT policy, (2) the UPDATE policy only checked owner_id, so a user could re-point
-- their own conversation at any twin id they could guess, and (3) the column was freely mutable. Additive and safe for
-- existing rows (every existing conversation was created on its owner's own twin).

-- 1. A twin id is only valid together with its owner: lets other tables reference the pair.
alter table public.twins
  add constraint twins_id_owner_key unique (id, owner_id);

-- 2. The conversation's (twin, owner) pair must be a real twin owned by that same user.
alter table public.conversations
  add constraint conversations_twin_owner_fkey
  foreign key (twin_id, owner_id) references public.twins (id, owner_id) on delete cascade;

-- 3. A conversation never changes character or owner after it is created.
create or replace function public.conversations_binding_immutable() returns trigger
language plpgsql set search_path = '' as $$
begin
  if new.twin_id is distinct from old.twin_id or new.owner_id is distinct from old.owner_id then
    raise exception 'a conversation cannot be moved to another character or owner' using errcode = '23514';
  end if;
  return new;
end $$;
revoke execute on function public.conversations_binding_immutable() from public, anon, authenticated;
create trigger conversations_binding_immutable before update on public.conversations
  for each row execute function public.conversations_binding_immutable();
