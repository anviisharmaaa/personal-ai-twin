import { useId } from "react";
import type { AddressForm, UserGender, UserIdentityRecord } from "../lib/api";
import { TextField } from "./ui";

/** The signed-in user's OWN optional identity: separate from every character's gender. All of it may be left blank. */
export type UserIdentityValue = { gender: UserGender | ""; custom: string; pronouns: string; pronounsCustom: boolean; form: AddressForm | "" };

export const GENDERS: { value: UserGender; label: string }[] = [
  { value: "woman", label: "Woman" }, { value: "man", label: "Man" }, { value: "non_binary", label: "Non-binary" },
  { value: "other", label: "Other / custom" }, { value: "prefer_not_to_say", label: "Prefer not to say" },
];
export const PRONOUNS = ["she/her", "he/him", "they/them"];

export const fromRecord = (p: Partial<UserIdentityRecord> | null | undefined): UserIdentityValue => ({
  gender: p?.user_gender ?? "", custom: p?.user_gender_custom ?? "", pronouns: p?.user_pronouns ?? "",
  pronounsCustom: !!p?.user_pronouns && !PRONOUNS.includes(p.user_pronouns), form: p?.user_address_form ?? "",
});

/** Explicit nulls clear a saved value; the server never infers anything. */
export const toPayload = (v: UserIdentityValue): UserIdentityRecord => ({
  user_gender: v.gender || null,
  user_gender_custom: v.gender === "other" ? v.custom.trim() || null : null,
  user_pronouns: v.pronouns.trim() || null,
  user_address_form: v.form || null,
});

export const sameValue = (a: UserIdentityValue, b: UserIdentityValue) => JSON.stringify(toPayload(a)) === JSON.stringify(toPayload(b));

const SELECT = "h-10 w-full rounded-[10px] border border-border bg-surface-2 px-3 text-sm";

export function UserIdentityFields({ value, onChange }: { value: UserIdentityValue; onChange: (v: UserIdentityValue) => void }) {
  const id = useId();
  const set = (patch: Partial<UserIdentityValue>) => onChange({ ...value, ...patch });
  const pronounChoice = value.pronounsCustom ? "__custom" : value.pronouns;
  return (
    <div className="space-y-5" role="group" aria-label="About you">
      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <label htmlFor={`${id}-g`} className="mb-1.5 block text-sm font-medium">Your gender (optional)</label>
          <select id={`${id}-g`} value={value.gender} className={SELECT}
            onChange={(e) => set({ gender: e.target.value as UserGender | "" })}>
            <option value="">Not answered</option>
            {GENDERS.map((g) => <option key={g.value} value={g.value}>{g.label}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor={`${id}-p`} className="mb-1.5 block text-sm font-medium">Your pronouns (optional)</label>
          <select id={`${id}-p`} value={pronounChoice} className={SELECT}
            onChange={(e) => e.target.value === "__custom" ? set({ pronounsCustom: true, pronouns: "" })
              : set({ pronounsCustom: false, pronouns: e.target.value })}>
            <option value="">Not specified</option>
            {PRONOUNS.map((p) => <option key={p} value={p}>{p}</option>)}
            <option value="__custom">Custom…</option>
          </select>
        </div>
      </div>
      {value.gender === "other" && (
        <TextField label="In your own words" value={value.custom} maxLength={40} onChange={(e) => set({ custom: e.target.value })}
          hint="Letters, spaces and basic punctuation only." />
      )}
      {value.pronounsCustom && (
        <TextField label="Your pronouns, in your own words" value={value.pronouns} maxLength={40} placeholder="e.g. xe/xem"
          onChange={(e) => set({ pronouns: e.target.value })} />
      )}
      <div>
        <label htmlFor={`${id}-f`} className="mb-1.5 block text-sm font-medium">How characters refer to you in gendered languages (optional)</label>
        <select id={`${id}-f`} value={value.form} className={SELECT} aria-describedby={`${id}-fh`}
          onChange={(e) => set({ form: e.target.value as AddressForm | "" })}>
          <option value="">No preference (use my gender above if it’s Woman or Man)</option>
          <option value="feminine">Feminine forms (Hindi: “tum thak gayi ho”)</option>
          <option value="masculine">Masculine forms (Hindi: “tum thak gaye ho”)</option>
          <option value="neutral">Avoid gendered forms about me</option>
        </select>
        <p id={`${id}-fh`} className="mt-1.5 text-sm text-muted">
          Only affects grammar in languages like Hindi, Hinglish and Urdu. It’s separate from your gender, and it’s never used to
          decide your personality, interests or role. Everything here is optional and stays your own choice.
        </p>
      </div>
    </div>
  );
}
