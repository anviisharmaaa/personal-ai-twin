-- The signed-in USER's own optional gender / pronouns / grammatical address preference. Additive only:
-- four nullable columns on the user's own profiles row (existing RLS: select/update where auth.uid() = id).
-- Existing rows keep NULL = "not specified". Nothing is dropped, rewritten or inferred.
-- This is NOT the character's gender (that lives in twins.appearance).
alter table public.profiles
  add column if not exists user_gender text
    check (user_gender in ('woman','man','non_binary','other','prefer_not_to_say')),
  add column if not exists user_gender_custom text
    check (user_gender_custom is null or char_length(user_gender_custom) between 1 and 40),
  add column if not exists user_pronouns text
    check (user_pronouns is null or char_length(user_pronouns) between 1 and 40),
  add column if not exists user_address_form text
    check (user_address_form in ('feminine','masculine','neutral'));
