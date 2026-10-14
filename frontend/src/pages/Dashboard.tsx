import { useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion, useReducedMotion } from "motion/react";
import { TwinAvatar } from "../components/TwinAvatar";
import { Button, Card, Chip, EmptyState, Notice, Skeleton } from "../components/ui";
import { useMe } from "../hooks/useMe";

export const SETUP_STEPS = [
  { id: "welcome", label: "Privacy & consent" },
  { id: "identity", label: "Identity" },
  { id: "personality", label: "Personality" },
] as const;

export function Dashboard() {
  const me = useMe();
  const nav = useNavigate();
  const reduce = useReducedMotion();

  useEffect(() => {
    // First-time users go straight into guided setup.
    if (me.data && !me.data.twin && !me.data.completed_steps.includes("welcome")) nav("/app/onboarding", { replace: true });
  }, [me.data, nav]);

  if (me.isLoading) return <div className="space-y-6"><Skeleton className="h-48" /><Skeleton className="h-32" /></div>;
  if (me.isError || !me.data) {
    return (
      <Notice tone="error">
        We couldn’t load your account. {(me.error as Error | undefined)?.message}{" "}
        <button className="underline" onClick={() => me.refetch()}>Try again</button>
      </Notice>
    );
  }

  const { twin, completed_steps: done } = me.data;
  const doneCount = SETUP_STEPS.filter((s) => done.includes(s.id)).length;
  const ready = doneCount === SETUP_STEPS.length;
  const name = me.data.profile?.display_name;

  return (
    <motion.div initial={reduce ? false : { opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.22 }} className="space-y-8">
      <Card className="relative overflow-hidden p-8 md:p-10">
        <div className="flex flex-col items-center gap-8 text-center md:flex-row md:text-left">
          <div className="p-7"><TwinAvatar twin={twin} size={160} /></div>
          <div className="min-w-0 flex-1">
            <p className="text-sm text-muted">{name ? `Welcome back, ${name}` : "Welcome"}</p>
            <h1 className="mt-1 text-3xl font-semibold tracking-tight md:text-4xl">{twin ? twin.name : "Your twin is waiting to be created"}</h1>
            <div className="mt-3 flex flex-wrap justify-center gap-2 md:justify-start">
              <Chip>AI representation</Chip>
              {ready && <Chip tone="ok">Foundation ready</Chip>}
            </div>
            <p className="mt-4 max-w-lg text-sm text-muted">
              {twin?.about || "A twin is an AI representation shaped by what you tell it. It is never you, and it never claims to be."}
            </p>
            <div className="mt-6 flex flex-wrap justify-center gap-3 md:justify-start">
              {!ready ? <Link to="/app/onboarding"><Button size="lg">Continue setup</Button></Link>
                : <Link to="/app/studio"><Button size="lg">Open Twin Studio</Button></Link>}
              {ready && <Link to="/app/onboarding"><Button size="lg" variant="secondary">Add a portrait</Button></Link>}
            </div>
          </div>
        </div>
      </Card>

      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <h2 className="text-base font-semibold">Setup progress</h2>
          <p className="mt-1 text-sm text-muted">{doneCount} of {SETUP_STEPS.length} foundation steps complete</p>
          <ol className="mt-4 space-y-2">
            {SETUP_STEPS.map((s) => (
              <li key={s.id} className="flex items-center gap-3 text-sm">
                <span className={`grid size-5 place-items-center rounded-full border text-[11px] ${done.includes(s.id) ? "border-success bg-success text-on-danger" : "border-border"}`}>{done.includes(s.id) ? "✓" : ""}</span>
                <span className={done.includes(s.id) ? "" : "text-muted"}>{s.label}</span>
              </li>
            ))}
          </ol>
          <p className="mt-4 text-sm text-muted">Memory review and your first conversation arrive in later releases.</p>
        </Card>

        <Card>
          <h2 className="text-base font-semibold">Recent conversations</h2>
          <div className="mt-4">
            <EmptyState title="Chat isn’t available yet" body="Conversations with your twin are the next thing we’re building. Your setup is saved and will be ready when they arrive." />
          </div>
        </Card>

        <Card>
          <h2 className="text-base font-semibold">Memories to review</h2>
          <p className="mt-2 text-sm text-muted">Memory import and review aren’t available yet, so nothing is waiting for your approval. When they arrive, nothing is remembered without your say-so.</p>
        </Card>

        <Card>
          <h2 className="text-base font-semibold">Voice & scheduled messages</h2>
          <p className="mt-2 text-sm text-muted">Voice messages and scheduled check-ins are planned, not active yet.</p>
          <div className="mt-3 flex gap-2"><Chip tone="soon">Voice · not yet</Chip><Chip tone="soon">Automations · not yet</Chip></div>
        </Card>
      </div>
    </motion.div>
  );
}
