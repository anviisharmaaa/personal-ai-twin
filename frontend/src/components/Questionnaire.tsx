import type { Question } from "../lib/api";

export type Answers = Record<string, string | string[]>;
const pretty = (s: string) => (s === "not_sure" ? "Not sure" : s.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()));

export function Questionnaire({ questions, value, onChange }: { questions: Question[]; value: Answers; onChange: (a: Answers) => void }) {
  const set = (q: Question, opt: string) => {
    const cur = value[q.id];
    if (!q.multi) {
      const next = { ...value };
      if (cur === opt) delete next[q.id]; else next[q.id] = opt;
      return onChange(next);
    }
    const list = Array.isArray(cur) ? cur : [];
    if (opt === "not_sure") return onChange({ ...value, [q.id]: list.includes(opt) ? [] : ["not_sure"] });
    const without = list.filter((x) => x !== "not_sure");
    const next = without.includes(opt) ? without.filter((x) => x !== opt) : [...without, opt].slice(0, q.max ?? 3);
    onChange({ ...value, [q.id]: next });
  };
  return (
    <div className="space-y-7">
      {questions.map((q) => {
        const cur = value[q.id];
        return (
          <fieldset key={q.id}>
            <legend className="mb-3 text-sm font-medium">{q.prompt}</legend>
            <div className="flex flex-wrap gap-2" role={q.multi ? "group" : "radiogroup"}>
              {[...q.options, "not_sure"].map((opt) => {
                const on = Array.isArray(cur) ? cur.includes(opt) : cur === opt;
                return (
                  <button key={opt} type="button" role={q.multi ? "checkbox" : "radio"} aria-checked={on}
                    onClick={() => set(q, opt)}
                    className={`h-10 rounded-full border px-4 text-sm transition duration-150 ${on ? "border-brand bg-brand text-on-brand" : "border-border bg-surface-2 hover:border-ring"}`}>
                    {pretty(opt)}
                  </button>
                );
              })}
            </div>
          </fieldset>
        );
      })}
    </div>
  );
}
