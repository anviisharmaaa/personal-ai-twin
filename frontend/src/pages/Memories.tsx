import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Button, Card, Chip, EmptyState, Notice, Skeleton, TextArea } from "../components/ui";
import {
  useApprove, useCandidates, useEditMemory, useForget, useLearningPref, useMemories, useProposals, useProposeFromMemory,
  useReject, useResolveProposal, useRevisions, useSetLearning, type Candidate, type Memory, type Proposal,
} from "../hooks/useChat";
import { ApiError } from "../lib/api";

const CATEGORY: Record<string, string> = {
  fact: "Fact", preference: "Preference", boundary: "Boundary", communication_style: "How they speak", trait: "Trait",
  context_behaviour: "Depends on the situation", correction: "Correction",
};
const EVIDENCE: Record<string, string> = {
  explicit_statement: "You said this", correction: "You corrected the twin", memory_request: "You asked to be remembered",
  repeated_pattern: "Seen in several of your messages",
};
const SECTION: Record<string, string> = {
  core_traits: "Core traits", speaking_style: "Speaking style", warmth_and_expressiveness: "Warmth and expressiveness",
  humour_and_playfulness: "Humour and playfulness", empathy_and_support: "Empathy and support",
  directness_and_disagreement: "Directness and disagreement", values_and_motivations: "Values and motivations",
  relationships_and_social: "Relationships and social life", interests_and_habits: "Interests and habits",
  communication_preferences: "Communication preferences", boundaries_and_careful_topics: "Boundaries and careful topics",
  response_patterns: "Response patterns",
};
const KIND: Record<string, string> = { correction: "A correction you made", new_evidence: "New evidence from your messages", contextual_exception: "A situation-specific exception" };
const MSG: Record<string, string> = {
  duplicate: "Madhuora already remembers this.", not_pending: "That was already handled.", section_full: "That section of the profile is full. Edit the profile directly or defer this.",
  source_gone: "The memory behind this was forgotten.", no_profile: "There is no interpretation of the character to change yet.", superseded: "That memory was replaced by a newer one.",
};
const say = (e: unknown) => (e instanceof ApiError ? MSG[e.code ?? ""] ?? e.message : "Something went wrong. Please try again.");

function Quotes({ items }: { items: { quote: string }[] }) {
  if (!items.length) return <p className="mt-2 text-xs text-muted">The conversation this came from has been deleted, so the quote is gone. You approved the memory itself, so it stays.</p>;
  return (
    <details className="mt-2 text-xs text-muted">
      <summary className="cursor-pointer">Where this came from</summary>
      <ul className="mt-1 space-y-1">{items.map((q, i) => <li key={i} className="border-l-2 border-border pl-2">“{q.quote}” <span className="text-[11px]">— your own message</span></li>)}</ul>
    </details>
  );
}

function LearningCard() {
  const pref = useLearningPref();
  const set = useSetLearning();
  const [open, setOpen] = useState(false);
  const [ok, setOk] = useState(false);
  if (pref.isLoading) return <Skeleton className="h-28" />;
  const on = pref.data?.enabled === true;
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Learning from conversations</h2>
          <p className="mt-1 text-sm text-muted">{on ? "On — you can ask Madhuora to review a conversation. Nothing is remembered until you approve it." : "Off — Madhuora doesn’t look for things to remember."}</p>
        </div>
        {on ? <Button variant="secondary" loading={set.isPending} onClick={() => set.mutate({ enabled: false })}>Turn off</Button>
          : <Button variant="secondary" onClick={() => setOpen((o) => !o)} aria-expanded={open}>Turn on…</Button>}
      </div>
      {on && <p className="mt-3 text-xs text-muted">Turning this off stops new reviews. It doesn’t delete anything already remembered — you can do that below.</p>}
      {!on && open && (
        <div className="mt-4 border-t border-border pt-4 text-sm">
          <p className="font-medium">What this does, exactly</p>
          <ul className="mt-2 list-disc space-y-1.5 pl-5 text-muted">
            <li>Only when you press “Review what Madhuora learned” on a conversation, the AI provider this server uses reads that conversation. It looks for things <strong className="text-fg">you</strong> wrote — facts, preferences, boundaries, corrections.</li>
            <li>It can only suggest. Each suggestion shows your own words as proof. <strong className="text-fg">Nothing is used in replies until you approve it</strong>, and you can edit, reject or forget any of it later.</li>
            <li>Madhuora’s own replies are never treated as evidence about you.</li>
            <li>This is saved notes that are looked up when relevant. It does <strong className="text-fg">not</strong> retrain or change the AI model.</li>
            <li>Right now this only runs on the local model; the conversation is not sent to a cloud AI service. Notes are stored in your Madhuora database like the rest of your twin.</li>
            <li>Your original description is never changed by this. Changes to the interpretation are only made if you accept them.</li>
          </ul>
          <label className="mt-4 flex items-start gap-2"><input type="checkbox" className="mt-1" checked={ok} onChange={(e) => setOk(e.target.checked)} /><span>I understand, and I want to turn this on.</span></label>
          {set.isError && <p role="alert" className="mt-2 text-danger">{say(set.error)}</p>}
          <div className="mt-3"><Button disabled={!ok} loading={set.isPending} onClick={() => set.mutate({ enabled: true, disclosure: pref.data?.current_disclosure_version }, { onSuccess: () => { setOpen(false); setOk(false); } })}>Turn on learning</Button></div>
        </div>
      )}
    </Card>
  );
}

function CandidateCard({ c }: { c: Candidate }) {
  const approve = useApprove();
  const reject = useReject();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(c.statement);
  const [conflict, setConflict] = useState<{ id: string; statement: string }[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const go = (resolution?: "keep_both" | "replace") => {
    setErr(null);
    approve.mutate({ id: c.id, statement: editing && text.trim() !== c.statement ? text.trim() : undefined, resolution }, {
      onError: (e) => {
        const d = e instanceof ApiError ? e : null;
        if (d?.code === "conflict") {
          // The server names what overlaps and waits for the user's choice; it never picks one itself.
          setConflict((d.extra?.conflicting as { id: string; statement: string }[] | undefined) ?? []);
        } else setErr(say(e));
      },
    });
  };
  return (
    <li className="rounded-[12px] border border-border bg-surface p-4">
      <div className="flex flex-wrap gap-2"><Chip>{CATEGORY[c.category] ?? c.category}</Chip><Chip>{EVIDENCE[c.evidence_type] ?? c.evidence_type}</Chip></div>
      {editing ? <TextArea label="Edit before approving" value={text} maxLength={240} fieldClassName="min-h-20" onChange={(e) => setText(e.target.value)} className="mt-3" />
        : <p className="mt-3 text-sm font-medium">{c.statement}</p>}
      <Quotes items={c.supporting} />
      {conflict && (
        <div className="mt-3"><Notice>This overlaps with something Madhuora already remembers{conflict.length ? `: “${conflict.map((m) => m.statement).join("”, “")}”` : ""}. Which do you want?
          <span className="mt-2 flex flex-wrap gap-2">
            <Button size="sm" onClick={() => go("replace")}>Replace the older one</Button>
            <Button size="sm" variant="secondary" onClick={() => go("keep_both")}>Keep both</Button>
            <Button size="sm" variant="ghost" onClick={() => setConflict(null)}>Not now</Button></span></Notice></div>
      )}
      {err && <p role="alert" className="mt-2 text-sm text-danger">{err}</p>}
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" loading={approve.isPending} onClick={() => go()}>{editing ? "Save and remember" : "Remember this"}</Button>
        <Button size="sm" variant="secondary" onClick={() => setEditing((e) => !e)}>{editing ? "Cancel edit" : "Edit first"}</Button>
        <Button size="sm" variant="ghost" loading={reject.isPending} onClick={() => reject.mutate({ id: c.id, reason: "wrong" })}>That’s not right</Button>
        <Button size="sm" variant="ghost" loading={reject.isPending} onClick={() => reject.mutate({ id: c.id, reason: "private" })}>Don’t keep this</Button>
      </div>
    </li>
  );
}

function MemoryCard({ m }: { m: Memory }) {
  const edit = useEditMemory();
  const forget = useForget();
  const propose = useProposeFromMemory();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(m.statement);
  const [section, setSection] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  return (
    <li className="rounded-[12px] border border-border bg-surface p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Chip>{CATEGORY[m.category] ?? m.category}</Chip><Chip>{EVIDENCE[m.evidence_type] ?? m.evidence_type}</Chip>
        {m.pinned && <Chip tone="ok">Pinned</Chip>}{m.edited && <Chip>Edited by you</Chip>}
      </div>
      {editing ? (
        <div className="mt-3">
          <TextArea label="Memory" value={text} maxLength={240} fieldClassName="min-h-20" onChange={(e) => setText(e.target.value)} />
          <div className="mt-2 flex gap-2">
            <Button size="sm" loading={edit.isPending} onClick={() => edit.mutate({ id: m.id, statement: text.trim() }, { onSuccess: () => setEditing(false), onError: (e) => setErr(say(e)) })}>Save</Button>
            <Button size="sm" variant="secondary" onClick={() => { setEditing(false); setText(m.statement); }}>Cancel</Button>
          </div>
        </div>
      ) : <p className="mt-3 text-sm font-medium">{m.statement}</p>}
      {m.scope && <p className="mt-1 text-xs text-muted">Applies to: {m.scope}</p>}
      <Quotes items={m.supporting} />
      {err && <p role="alert" className="mt-2 text-sm text-danger">{err}</p>}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button size="sm" variant="secondary" onClick={() => setEditing(true)}>Edit</Button>
        <Button size="sm" variant="secondary" loading={edit.isPending && !editing} onClick={() => edit.mutate({ id: m.id, pinned: !m.pinned })}>{m.pinned ? "Unpin" : "Pin"}</Button>
        <Button size="sm" variant="ghost" loading={forget.isPending} onClick={() => forget.mutate({ id: m.id, incorrect: false })}>Forget</Button>
        <Button size="sm" variant="ghost" loading={forget.isPending} onClick={() => forget.mutate({ id: m.id, incorrect: true })}>This is wrong</Button>
      </div>
      <div className="mt-3 flex flex-wrap items-end gap-2 border-t border-border pt-3">
        <label className="text-xs text-muted">Suggest a change to the profile
          <select value={section} onChange={(e) => { setSection(e.target.value); setDone(false); }} className="mt-1 block h-9 rounded-[10px] border border-border bg-surface-2 px-2 text-sm text-fg">
            <option value="">Choose a section…</option>
            {Object.entries(SECTION).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select></label>
        <Button size="sm" variant="secondary" disabled={!section} loading={propose.isPending}
          onClick={() => propose.mutate({ id: m.id, section }, { onSuccess: () => setDone(true), onError: (e) => setErr(say(e)) })}>Create suggestion</Button>
        {done && <span role="status" className="text-xs text-success">Added to “Profile updates”.</span>}
      </div>
    </li>
  );
}

function ProposalCard({ p }: { p: Proposal }) {
  const resolve = useResolveProposal();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(p.proposed_text);
  const [err, setErr] = useState<string | null>(null);
  const act = (action: "accept" | "reject" | "defer") =>
    resolve.mutate({ id: p.id, action, text: action === "accept" && editing ? text.trim() : undefined }, { onError: (e) => setErr(say(e)) });
  return (
    <li className="rounded-[12px] border border-border bg-surface p-4">
      <div className="flex flex-wrap gap-2"><Chip>{SECTION[p.section] ?? p.section}</Chip><Chip>{KIND[p.kind] ?? p.kind}</Chip>{p.status === "deferred" && <Chip>Saved for later</Chip>}</div>
      <p className="mt-3 text-xs text-muted">Would add to the interpretation of your twin:</p>
      {editing ? <TextArea label="Wording" value={text} maxLength={320} fieldClassName="min-h-20" onChange={(e) => setText(e.target.value)} />
        : <p className="mt-1 text-sm font-medium">{p.proposed_text}</p>}
      {p.evidence.length > 0 && <Quotes items={p.evidence.map((q) => ({ quote: q }))} />}
      <p className="mt-2 text-xs text-muted">Your original description stays exactly as you wrote it. The current interpretation is saved first, so you can always see what it was before.</p>
      {err && <p role="alert" className="mt-2 text-sm text-danger">{err}</p>}
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" loading={resolve.isPending} onClick={() => act("accept")}>{editing ? "Save and add" : "Add to profile"}</Button>
        <Button size="sm" variant="secondary" onClick={() => setEditing((e) => !e)}>{editing ? "Cancel edit" : "Edit wording"}</Button>
        <Button size="sm" variant="ghost" onClick={() => act("defer")}>Decide later</Button>
        <Button size="sm" variant="ghost" onClick={() => act("reject")}>No thanks</Button>
      </div>
    </li>
  );
}

function List<T>({ q, empty, render }: { q: { isLoading: boolean; isError: boolean; data?: T[] }; empty: ReactNode; render: (x: T) => ReactNode }) {
  if (q.isLoading) return <Skeleton className="h-24" />;
  if (q.isError) return <Notice tone="error">Couldn’t load this. Please refresh.</Notice>;
  if (!q.data?.length) return <>{empty}</>;
  return <ul className="flex flex-col gap-3">{q.data.map(render)}</ul>;
}

type Tab = "review" | "remembered" | "updates" | "history";
export function Memories() {
  const [tab, setTab] = useState<Tab>("review");
  const cands = useCandidates();
  const mems = useMemories();
  const props = useProposals();
  const revs = useRevisions();
  useEffect(() => { document.title = "Memories · Madhuora"; }, []);
  const tabs: [Tab, string, number | undefined][] = [
    ["review", "To review", cands.data?.length], ["remembered", "Remembered", mems.data?.length],
    ["updates", "Profile updates", props.data?.length], ["history", "History", revs.data?.length],
  ];
  return (
    <div>
      <h1 className="text-3xl font-semibold tracking-tight">Memories</h1>
      <p className="mt-3 max-w-xl text-muted">What Madhuora may remember from your conversations — only after you approve it. Everything here is yours to edit or forget.</p>
      <div className="mt-6"><LearningCard /></div>

      <div role="tablist" aria-label="Memory sections" className="mt-8 flex flex-wrap gap-1 border-b border-border">
        {tabs.map(([id, label, n]) => (
          <button key={id} role="tab" id={`tab-${id}`} aria-selected={tab === id} aria-controls={`panel-${id}`} onClick={() => setTab(id)}
            className={`-mb-px h-10 border-b-2 px-3 text-sm ${tab === id ? "border-brand font-medium" : "border-transparent text-muted hover:text-fg"}`}>
            {label}{n ? <span className="ml-1.5 rounded-full bg-surface-2 px-1.5 text-xs">{n}</span> : null}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} className="mt-5">
        {tab === "review" && <List q={cands} render={(c) => <CandidateCard key={c.id} c={c} />}
          empty={<EmptyState title="Nothing to review" body="Open a conversation and choose “Review what Madhuora learned”. Suggestions appear here, and nothing is remembered until you approve it." action={<Link to="/app/conversations" className="text-sm font-medium text-accent underline underline-offset-4">Go to Conversations</Link>} />} />}
        {tab === "remembered" && <List q={mems} render={(m) => <MemoryCard key={m.id} m={m} />}
          empty={<EmptyState title="Nothing remembered yet" body="Approved memories appear here. Only these are ever used to shape a reply." />} />}
        {tab === "updates" && <List q={props} render={(p) => <ProposalCard key={p.id} p={p} />}
          empty={<EmptyState title="No profile updates waiting" body="When a correction you made seems to change how your twin should speak or act, a suggestion appears here. The profile only changes if you accept it." />} />}
        {tab === "history" && <List q={revs} render={(r) => (
          <li key={r.id} className="rounded-[12px] border border-border bg-surface p-4 text-sm">
            <p className="font-medium">{r.reason === "regenerated" ? "Interpretation re-made from your description" : "Before you accepted a suggestion"}</p>
            <p className="text-xs text-muted">{new Date(r.created_at).toLocaleString()}</p>
            <p className="mt-2 text-muted">{String((r.profile as { summary?: string }).summary ?? "")}</p>
          </li>)}
          empty={<EmptyState title="No changes yet" body="Each time the interpretation is changed from a suggestion, the earlier version is kept here." />} />}
      </div>
    </div>
  );
}
