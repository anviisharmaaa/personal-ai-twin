export function Segmented<T extends string>({ label, value, options, onChange }: {
  label: string; value: T | undefined; options: { value: T; label: string }[]; onChange: (v: T) => void;
}) {
  return (
    <div>
      <div className="mb-2 text-sm font-medium" id={`seg-${label}`}>{label}</div>
      <div role="radiogroup" aria-labelledby={`seg-${label}`} className="inline-flex flex-wrap gap-1 rounded-[10px] border border-border bg-surface-2 p-1">
        {options.map((o) => (
          <button key={o.value} type="button" role="radio" aria-checked={value === o.value} onClick={() => onChange(o.value)}
            className={`h-9 rounded-[6px] px-3 text-sm transition duration-150 ${value === o.value ? "bg-brand text-on-brand" : "text-muted hover:text-fg"}`}>
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}
