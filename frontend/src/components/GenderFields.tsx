import { GENDER_OPTIONS } from "../lib/api";
import type { Gender } from "../lib/api";
import { Segmented } from "./Segmented";
import { TextField } from "./ui";

/** Gender and pronouns the character uses for itself. They guide grammar and self-reference in replies (for example
 *  Hindi verb endings); they never decide personality. */
export function GenderFields({ gender, pronouns, onChange }: {
  gender: Gender | undefined; pronouns: string | undefined; onChange: (g: Gender | undefined, p: string | undefined) => void;
}) {
  const current = gender ?? "unspecified";
  const suggested = GENDER_OPTIONS.find((o) => o.value === current)?.pronouns ?? "";
  return (
    <div className="space-y-3" role="group" aria-label="Gender and pronouns">
      <Segmented label="Gender" value={current} options={GENDER_OPTIONS.map(({ value, label }) => ({ value, label }))}
        onChange={(v) => onChange(v, pronouns)} />
      <TextField label="Pronouns (optional)" value={pronouns ?? ""} maxLength={40} placeholder={suggested || "e.g. she/her"}
        onChange={(e) => onChange(gender, e.target.value)}
        hint="Used so replies agree with who the character is (in Hindi, “kar rahi hoon” vs “kar raha hoon”). Left blank, we use the usual pronouns for the gender." />
    </div>
  );
}
