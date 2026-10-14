import { forwardRef, useId, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type TextareaHTMLAttributes } from "react";

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md" | "lg";
  loading?: boolean;
};

const sizes = { sm: "h-9 px-3 text-sm", md: "h-10 px-4 text-sm", lg: "h-12 px-6 text-base" };
const variants = {
  primary: "bg-brand text-on-brand hover:brightness-110 active:brightness-95",
  secondary: "bg-surface text-fg border border-border hover:bg-surface-2",
  ghost: "text-fg hover:bg-surface-2",
  danger: "bg-danger text-on-danger hover:brightness-110",
};

export const Button = forwardRef<HTMLButtonElement, BtnProps>(function Button(
  { variant = "primary", size = "md", loading, disabled, children, className = "", ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={`inline-flex items-center justify-center gap-2 rounded-[10px] font-medium transition duration-150 disabled:cursor-not-allowed disabled:opacity-50 ${sizes[size]} ${variants[variant]} ${className}`}
      {...rest}
    >
      {loading && <span className="size-4 animate-spin rounded-full border-2 border-current border-t-transparent" aria-hidden />}
      {children}
    </button>
  );
});

type FieldBase = { label: string; hint?: string; error?: string | null };

export const TextField = forwardRef<HTMLInputElement, FieldBase & InputHTMLAttributes<HTMLInputElement>>(
  function TextField({ label, hint, error, className = "", ...rest }, ref) {
    const id = useId();
    return (
      <div className={className}>
        <label htmlFor={id} className="mb-1.5 block text-sm font-medium">{label}</label>
        <input
          id={id}
          ref={ref}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${id}-e` : hint ? `${id}-h` : undefined}
          className="h-10 w-full rounded-[10px] border border-border bg-surface-2 px-3 text-sm placeholder:text-muted/70 focus:border-ring"
          {...rest}
        />
        {error ? <p id={`${id}-e`} role="alert" className="mt-1.5 text-sm text-danger">{error}</p>
          : hint ? <p id={`${id}-h`} className="mt-1.5 text-sm text-muted">{hint}</p> : null}
      </div>
    );
  },
);

export const TextArea = forwardRef<HTMLTextAreaElement, FieldBase & { fieldClassName?: string } & TextareaHTMLAttributes<HTMLTextAreaElement>>(
  function TextArea({ label, hint, error, className = "", fieldClassName = "min-h-28", ...rest }, ref) {
    const id = useId();
    return (
      <div className={className}>
        <label htmlFor={id} className="mb-1.5 block text-sm font-medium">{label}</label>
        <textarea
          id={id}
          ref={ref}
          aria-invalid={error ? true : undefined}
          aria-describedby={[error && `${id}-e`, hint && `${id}-h`].filter(Boolean).join(" ") || undefined}
          className={`w-full rounded-[10px] border border-border bg-surface-2 px-3 py-2 text-sm placeholder:text-muted/70 focus:border-ring ${fieldClassName}`}
          {...rest}
        />
        {error && <p id={`${id}-e`} role="alert" className="mt-1.5 text-sm text-danger">{error}</p>}
        {hint && <p id={`${id}-h`} className="mt-1.5 text-sm text-muted">{hint}</p>}
      </div>
    );
  },
);

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-[16px] border border-border bg-surface p-6 ${className}`}>{children}</section>;
}

export function Chip({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "soon" | "ok" }) {
  const t = { neutral: "border-border text-muted", soon: "border-border text-muted", ok: "border-success/50 text-success" }[tone];
  return <span className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${t}`}>{children}</span>;
}

export function Notice({ tone = "info", children }: { tone?: "info" | "error" | "success"; children: ReactNode }) {
  const c = { info: "border-border bg-surface-2", error: "border-danger/60 bg-surface-2 text-danger", success: "border-success/50 bg-surface-2 text-success" }[tone];
  return <div role={tone === "error" ? "alert" : "status"} className={`rounded-[10px] border px-4 py-3 text-sm ${c}`}>{children}</div>;
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton ${className}`} aria-hidden />;
}

export function EmptyState({ title, body, action }: { title: string; body: string; action?: ReactNode }) {
  return (
    <div className="rounded-[16px] border border-dashed border-border p-8 text-center">
      <h3 className="text-base font-semibold">{title}</h3>
      <p className="mx-auto mt-2 max-w-md text-sm text-muted">{body}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
