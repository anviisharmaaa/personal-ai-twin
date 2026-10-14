import { useEffect, useMemo, useState } from "react";
import { Link, useBlocker } from "react-router-dom";
import { PortraitEditor } from "../components/PortraitEditor";
import { CharacterEditor } from "../components/CharacterEditor";
import { Segmented } from "../components/Segmented";
import { TwinAvatar } from "../components/TwinAvatar";
import { Button, Card, EmptyState, Notice, Skeleton, TextArea, TextField } from "../components/ui";
import { useMe, useSaveTwin } from "../hooks/useMe";
import type { CharacterState, Twin } from "../lib/api";

type Form = {
  name: string; about: string;
  appearance: { framing?: string; background?: string; lighting?: string };
};
const TABS = ["Identity", "Character", "Appearance"] as const;

const fromTwin = (t: Twin): Form => ({
  name: t.name, about: t.about ?? "",
  appearance: { framing: t.appearance.framing, background: t.appearance.background, lighting: t.appearance.lighting },
});
const strip = (o: object) => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== undefined));

export function TwinStudio() {
  const me = useMe();
  if (me.isLoading) return <div className="space-y-4"><Skeleton className="h-10 w-64" /><Skeleton className="h-96" /></div>;
  if (me.isError || !me.data) return <Notice tone="error">We couldn’t load your twin. <button className="underline" onClick={() => me.refetch()}>Try again</button></Notice>;
  if (!me.data.twin) {
    return (<div><h1 className="text-3xl font-semibold tracking-tight">Twin Studio</h1>
      <div className="mt-8"><EmptyState title="No twin yet" body="Create your twin’s identity first, then come back here to refine it."
        action={<Link to="/app/onboarding"><Button>Start setup</Button></Link>} /></div></div>);
  }
  return <Studio twin={me.data.twin} character={me.data.character!} consentGranted={me.data.ai_consent.granted} key={me.data.twin.id} />;
}

function Studio({ twin, character, consentGranted }: { twin: Twin; character: CharacterState; consentGranted: boolean }) {
  const saveTwin = useSaveTwin();
  const [tab, setTab] = useState<(typeof TABS)[number]>("Identity");
  const [baseline, setBaseline] = useState<Form>(() => fromTwin(twin));
  const [form, setForm] = useState<Form>(baseline);
  const [err, setErr] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const [charDirty, setCharDirty] = useState(false);
  const formDirty = useMemo(() => JSON.stringify(form) !== JSON.stringify(baseline), [form, baseline]);
  const dirty = formDirty || charDirty;
  const blocker = useBlocker(({ currentLocation, nextLocation }) => dirty && currentLocation.pathname !== nextLocation.pathname);
  useEffect(() => {
    if (!dirty) return;
    const h = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    addEventListener("beforeunload", h);
    return () => removeEventListener("beforeunload", h);
  }, [dirty]);

  const set = <K extends keyof Form>(k: K, v: Form[K]) => { setSaved(false); setForm((f) => ({ ...f, [k]: v })); };
  const save = async () => {
    setErr(null);
    if (!form.name.trim()) { setTab("Identity"); return setErr("Your twin needs a name."); }
    try {
      // Changes stay in the form if either request fails, so nothing is lost.
      await saveTwin.mutateAsync({ name: form.name.trim(), about: form.about.trim(), appearance: strip(form.appearance) });
      setBaseline(form);
      setSaved(true);
    } catch (e) { setErr(e instanceof Error ? e.message : "Couldn’t save. Your changes are still here — try again."); }
  };

  return (
    <div className="pb-24">
      <div className="flex flex-wrap items-center gap-6">
        <TwinAvatar twin={{ ...twin, name: form.name || twin.name, appearance: { ...twin.appearance, ...form.appearance } }} size={88} orbit={false} />
        <div><h1 className="text-3xl font-semibold tracking-tight">Twin Studio</h1><p className="mt-1 text-sm text-muted">Describe who {twin.name} is and how they look. This is an AI representation, not the person.</p></div>
      </div>

      <div role="tablist" aria-label="Twin settings" className="mt-8 flex gap-1 overflow-x-auto border-b border-border">
        {TABS.map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
            className={`h-11 whitespace-nowrap border-b-2 px-4 text-sm transition duration-150 ${tab === t ? "border-accent font-medium" : "border-transparent text-muted hover:text-fg"}`}>{t}</button>
        ))}
      </div>

      <Card className="mt-6" >
        <div role="tabpanel" aria-label={tab}>
          {tab === "Identity" && (
            <div className="space-y-5">
              <TextField label="Twin’s name" value={form.name} maxLength={80} onChange={(e) => set("name", e.target.value)} error={!form.name.trim() ? "A name is required." : null} />
              <TextArea label="About" value={form.about} maxLength={2000} onChange={(e) => set("about", e.target.value)} hint={`${form.about.length}/2000`} />
              <p className="text-sm text-muted">Twin type: <strong>Yourself</strong>. Twins of other people require consent and review and aren’t available yet.</p>
            </div>
          )}
          {tab === "Character" && (
            <CharacterEditor twin={twin} character={character} consentGranted={consentGranted} mode="studio" onDirtyChange={setCharDirty} />
          )}
          {tab === "Appearance" && (
            <div className="space-y-8">
              <PortraitEditor twin={twin} />
              <div className="space-y-6 border-t border-border pt-6">
                <Segmented label="Framing" value={form.appearance.framing as "bust"} options={[{ value: "close", label: "Close" }, { value: "bust", label: "Bust" }, { value: "wide", label: "Wide" }]} onChange={(v) => set("appearance", { ...form.appearance, framing: v })} />
                <Segmented label="Backdrop" value={form.appearance.background as "wine"} options={[{ value: "ivory", label: "Ivory" }, { value: "wine", label: "Wine" }, { value: "maroon", label: "Maroon" }, { value: "gold", label: "Gold" }]} onChange={(v) => set("appearance", { ...form.appearance, background: v })} />
                <Segmented label="Lighting" value={form.appearance.lighting as "soft"} options={[{ value: "soft", label: "Soft" }, { value: "warm", label: "Warm" }, { value: "neutral", label: "Neutral" }]} onChange={(v) => set("appearance", { ...form.appearance, lighting: v })} />
                <p className="text-sm text-muted">Appearance settings only change framing, backdrop and lighting. They never alter a face.</p>
              </div>
            </div>
          )}
        </div>
      </Card>

      {tab !== "Character" && <div className="fixed bottom-0 left-0 right-0 z-20 border-t border-border bg-surface/95 px-4 py-3 md:px-8 backdrop-blur md:left-[var(--sidebar,248px)]">
        <div className="mx-auto flex max-w-[960px] items-center justify-between gap-3 md:px-4">
          <p role="status" className="text-sm text-muted">{err ? <span className="text-danger">{err}</span> : formDirty ? "Unsaved changes" : saved ? "All changes saved" : "No changes"}</p>
          <div className="flex gap-2">
            <Button variant="ghost" disabled={!formDirty || saveTwin.isPending} onClick={() => { setForm(baseline); setErr(null); }}>Discard</Button>
            <Button disabled={!formDirty} loading={saveTwin.isPending} onClick={save}>Save changes</Button>
          </div>
        </div>
      </div>}

      {blocker.state === "blocked" && (
        <div role="alertdialog" aria-modal="true" aria-label="Unsaved changes" className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4">
          <div className="w-full max-w-sm rounded-[24px] border border-border bg-surface p-6">
            <h3 className="text-lg font-semibold">Leave without saving?</h3>
            <p className="mt-2 text-sm text-muted">You have unsaved changes. If you leave now they will be lost.</p>
            <div className="mt-5 flex justify-end gap-2">
              <Button variant="ghost" onClick={() => blocker.reset()}>Keep editing</Button>
              <Button variant="danger" onClick={() => blocker.proceed()}>Leave</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
