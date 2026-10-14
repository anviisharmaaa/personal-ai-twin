import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { Icon } from "../components/Icon";
import { PortraitEditor } from "../components/PortraitEditor";
import { Questionnaire, type Answers } from "../components/Questionnaire";
import { Button, Card, Chip, Notice, Skeleton, TextArea, TextField } from "../components/ui";
import {
  useCompleteStep, useGrantConsent, useMe, useQuestionnaire, useSavePersonality, useSaveProfile, useSaveTwin,
} from "../hooks/useMe";

const STEPS = [
  { id: "welcome", title: "Privacy" },
  { id: "identity", title: "Identity" },
  { id: "personality", title: "Personality" },
  { id: "refinements", title: "Portrait", optional: true },
] as const;
type StepId = (typeof STEPS)[number]["id"];
const LATER = ["Import your own material", "Review proposed memories", "Your first conversation"];
const msg = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong. Please try again.");

export function Onboarding() {
  const me = useMe();
  const nav = useNavigate();
  const reduce = useReducedMotion();
  const [step, setStep] = useState<StepId | null>(null);

  const done = useMemo(() => new Set(me.data?.completed_steps ?? []), [me.data]);
  useEffect(() => {
    if (me.data && step === null) setStep(STEPS.find((s) => !done.has(s.id))?.id ?? "refinements");
  }, [me.data, step, done]);

  if (me.isLoading || !me.data || step === null) return <div className="space-y-4"><Skeleton className="h-10 w-64" /><Skeleton className="h-72" /></div>;
  if (me.isError) return <Notice tone="error">We couldn’t load your setup. <button className="underline" onClick={() => me.refetch()}>Try again</button></Notice>;

  const idx = STEPS.findIndex((s) => s.id === step);
  const canOpen = (i: number) => i === 0 || STEPS.slice(0, i).filter((s) => !("optional" in s)).every((s) => done.has(s.id));
  const next = () => (idx + 1 < STEPS.length ? setStep(STEPS[idx + 1].id) : nav("/app"));

  return (
    <div>
      <h1 className="text-3xl font-semibold tracking-tight">Set up your twin</h1>
      <p className="mt-2 text-muted">Your progress is saved as you go. You can stop and come back any time.</p>
      <div className="mt-8 grid gap-8 md:grid-cols-[220px_1fr]">
        <ol aria-label="Setup steps" className="flex gap-2 overflow-x-auto md:flex-col md:overflow-visible">
          {STEPS.map((s, i) => {
            const open = canOpen(i);
            return (
              <li key={s.id}>
                <button disabled={!open} aria-current={s.id === step ? "step" : undefined} onClick={() => setStep(s.id)}
                  className={`flex h-11 w-full items-center gap-3 whitespace-nowrap rounded-[10px] px-3 text-sm transition duration-150 disabled:opacity-50 ${s.id === step ? "bg-surface-2 font-medium" : "hover:bg-surface-2"}`}>
                  <span className={`grid size-6 place-items-center rounded-full border text-xs ${done.has(s.id) ? "border-success bg-success text-on-danger" : "border-border"}`}>
                    {done.has(s.id) ? <Icon name="check" size={14} /> : i + 1}
                  </span>
                  <span>{s.title}{"optional" in s && <span className="ml-1 text-muted">(optional)</span>}</span>
                </button>
              </li>
            );
          })}
          {LATER.map((l) => (
            <li key={l} className="flex items-center gap-3 whitespace-nowrap px-3 py-2 text-sm text-muted"><Icon name="lock" size={16} /><span>{l}</span></li>
          ))}
        </ol>

        <AnimatePresence mode="wait">
          <motion.div key={step} initial={reduce ? false : { opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} exit={reduce ? undefined : { opacity: 0 }} transition={{ duration: 0.2 }}>
            {step === "welcome" && <Welcome onDone={next} />}
            {step === "identity" && <Identity onDone={next} />}
            {step === "personality" && <Personality onDone={next} />}
            {step === "refinements" && <Portrait onFinish={() => nav("/app")} />}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
}

function Welcome({ onDone }: { onDone: () => void }) {
  const me = useMe();
  const consent = me.data!.ai_consent;
  const grant = useGrantConsent(consent.current_version);
  const complete = useCompleteStep();
  const [agree, setAgree] = useState(consent.granted);
  const [err, setErr] = useState<string | null>(null);
  const go = async () => {
    setErr(null);
    try {
      if (!consent.granted) await grant.mutateAsync();
      await complete.mutateAsync("welcome");
      onDone();
    } catch (e) { setErr(msg(e)); }
  };
  return (
    <Card>
      <h2 className="text-xl font-semibold">Before we begin</h2>
      <ul className="mt-4 space-y-3 text-sm">
        <li><strong>Your twin is an AI representation.</strong> It is clearly labelled as one. It is not you, doesn’t have your experiences or consciousness, and never claims to.</li>
        <li><strong>Your data is stored in Mumbai</strong> (India) with our database provider, and encrypted in transit. We do not claim end-to-end encryption.</li>
        <li><strong>Replies are generated by an AI provider</strong> (currently OpenAI, which processes data outside India). Only what’s needed for each reply is sent. Chat isn’t live yet, but we record your decision now.</li>
        <li><strong>You’re in control.</strong> You can withdraw this consent any time in Settings. Nothing is remembered long-term without your approval.</li>
      </ul>
      <label className="mt-6 flex items-start gap-3 text-sm">
        <input type="checkbox" className="mt-1 size-4" checked={agree} disabled={consent.granted} onChange={(e) => setAgree(e.target.checked)} />
        <span>I understand, and I agree to my twin’s information being processed by an external AI provider for the purposes above.{consent.granted && <span className="text-success"> Recorded (v{consent.version}).</span>}</span>
      </label>
      {err && <div className="mt-4"><Notice tone="error">{err}</Notice></div>}
      <div className="mt-6 flex justify-end"><Button size="lg" disabled={!agree} loading={grant.isPending || complete.isPending} onClick={go}>Agree and continue</Button></div>
    </Card>
  );
}

function Identity({ onDone }: { onDone: () => void }) {
  const me = useMe();
  const twin = me.data!.twin;
  const [name, setName] = useState(twin?.name ?? "");
  const [display, setDisplay] = useState(me.data!.profile?.display_name ?? "");
  const [about, setAbout] = useState(twin?.about ?? "");
  const saveTwin = useSaveTwin();
  const saveProfile = useSaveProfile();
  const complete = useCompleteStep();
  const [err, setErr] = useState<string | null>(null);
  const [touched, setTouched] = useState(false);
  const nameErr = touched && !name.trim() ? "Give your twin a name." : null;
  const go = async () => {
    setTouched(true);
    if (!name.trim()) return;
    setErr(null);
    try {
      await saveTwin.mutateAsync({ name: name.trim(), about: about.trim() });
      if (display.trim() !== (me.data!.profile?.display_name ?? "")) await saveProfile.mutateAsync({ display_name: display.trim() });
      await complete.mutateAsync("identity");
      onDone();
    } catch (e) { setErr(msg(e)); }
  };
  return (
    <Card>
      <h2 className="text-xl font-semibold">Who is this twin?</h2>
      <p className="mt-1 text-sm text-muted">For now a twin represents you. Twins of other people need consent and review, and aren’t available yet.</p>
      <div className="mt-6 space-y-5">
        <TextField label="Twin’s name" value={name} onChange={(e) => setName(e.target.value)} maxLength={80} error={nameErr} placeholder="e.g. Anvi" />
        <TextField label="What should we call you? (optional)" value={display} onChange={(e) => setDisplay(e.target.value)} maxLength={80} />
        <TextArea label="A few words about the twin (optional)" value={about} onChange={(e) => setAbout(e.target.value)} maxLength={2000}
          hint={`${about.length}/2000 · Shown on your dashboard. Keep anything private out of here.`} />
      </div>
      {err && <div className="mt-4"><Notice tone="error">{err}</Notice></div>}
      <div className="mt-6 flex justify-end"><Button size="lg" onClick={go} loading={saveTwin.isPending || complete.isPending}>Save and continue</Button></div>
    </Card>
  );
}

function Personality({ onDone }: { onDone: () => void }) {
  const me = useMe();
  const q = useQuestionnaire();
  const [answers, setAnswers] = useState<Answers>(me.data!.twin?.personality.answers ?? {});
  const save = useSavePersonality();
  const complete = useCompleteStep();
  const [err, setErr] = useState<string | null>(null);
  const run = async (a: Answers) => {
    setErr(null);
    try { await save.mutateAsync(a); await complete.mutateAsync("personality"); onDone(); } catch (e) { setErr(msg(e)); }
  };
  return (
    <Card>
      <h2 className="text-xl font-semibold">How does your twin communicate?</h2>
      <p className="mt-1 text-sm text-muted">Six quick questions. “Not sure” is always fine, and you can change everything later in Twin Studio.</p>
      <div className="mt-6">
        {q.isLoading && <Skeleton className="h-48" />}
        {q.isError && <Notice tone="error">Couldn’t load the questions. <button className="underline" onClick={() => q.refetch()}>Try again</button></Notice>}
        {q.data && <Questionnaire questions={q.data.questions} value={answers} onChange={setAnswers} />}
      </div>
      {err && <div className="mt-4"><Notice tone="error">{err}</Notice></div>}
      <div className="mt-6 flex flex-wrap justify-end gap-3">
        <Button variant="ghost" onClick={() => run({})} disabled={save.isPending || complete.isPending}>Skip for now</Button>
        <Button size="lg" onClick={() => run(answers)} loading={save.isPending || complete.isPending} disabled={!q.data}>Save and continue</Button>
      </div>
    </Card>
  );
}

function Portrait({ onFinish }: { onFinish: () => void }) {
  const me = useMe();
  const complete = useCompleteStep();
  const [err, setErr] = useState<string | null>(null);
  const twin = me.data!.twin;
  const finish = async () => {
    setErr(null);
    try { await complete.mutateAsync("refinements"); onFinish(); } catch (e) { setErr(msg(e)); }
  };
  return (
    <Card>
      <div className="flex items-center gap-3"><h2 className="text-xl font-semibold">Add a portrait</h2><Chip>Optional</Chip></div>
      <p className="mt-1 text-sm text-muted">This is a still image only — no voice or animated avatar yet.</p>
      <div className="mt-6">{twin ? <PortraitEditor twin={twin} /> : <Notice>Create your twin’s identity first.</Notice>}</div>
      {err && <div className="mt-4"><Notice tone="error">{err}</Notice></div>}
      <div className="mt-6 flex flex-wrap justify-end gap-3">
        <Button variant="ghost" onClick={onFinish}>Skip for now</Button>
        <Button size="lg" onClick={finish} loading={complete.isPending}>Finish setup</Button>
      </div>
    </Card>
  );
}
