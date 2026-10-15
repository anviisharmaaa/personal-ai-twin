import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Icon } from "../components/Icon";
import { Button, Chip, Notice, Skeleton } from "../components/ui";
import {
  K, useChatStatus, useConversations, useCreateConversation, useDeleteConversation, useLearningPref, useMemories,
  useMessages, useReviewState, useStartReview, type Message,
} from "../hooks/useChat";
import { ApiError } from "../lib/api";
import { StreamError, streamMessage, type StartedInfo } from "../lib/sse";

const REASONS: Record<string, { text: string; to?: string; label?: string }> = {
  no_twin: { text: "Create your twin’s identity first.", to: "/app/onboarding", label: "Set up your twin" },
  consent_required: { text: "Chat needs your permission to process text with the AI provider this server uses.", to: "/app/settings", label: "Open Settings" },
  no_profile: { text: "Chat uses the validated interpretation of your description. Understand the character first.", to: "/app/studio", label: "Open Twin Studio" },
  ai_disabled: { text: "AI is temporarily switched off on this server." },
  ai_off: { text: "No AI provider is selected on this server, so chat is off." },
  not_configured: { text: "The chosen AI provider isn’t fully set up on this server." },
  chat_provider_unsupported: { text: "Chat isn’t enabled for the AI provider this server uses. Personal conversations stay off the NVIDIA trial endpoint, and paid OpenAI chat isn’t switched on." },
};

const ERRORS: Record<string, string> = {
  local_unavailable: "Ollama isn’t running or couldn’t be reached.",
  local_model_missing: "The chosen model isn’t installed in Ollama.",
  first_token_timeout: "The model took too long to start answering.",
  generation_timeout: "The model stopped answering part-way through.",
  empty_response: "The model returned an empty reply.",
  invalid_stream: "The reply stream was garbled.",
  interrupted: "The connection was interrupted before the reply finished.",
  truncated: "The reply was cut off at the length limit.",
  persist_failed: "The reply couldn’t be saved.",
  model_busy: "The local model is busy with another job. Try again in a moment.",
  rate_limited: "You’ve sent a lot of messages this hour. Please try again later.",
  in_progress: "A reply is already being written in this conversation.",
  consent_required: "Consent for this AI provider is missing or out of date.",
  no_profile: "There is no interpretation of the character yet.",
  too_long: "That message is too long.",
  cancelled: "You stopped this reply.",
};
const errText = (code: string, fallback?: string) => ERRORS[code] ?? fallback ?? "Something went wrong.";

const newKey = () => (crypto.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`).replace(/[^A-Za-z0-9_-]/g, "");

type Pending = {
  key: string; text: string; reply: string; phase: "waiting" | "streaming" | "failed"; started?: StartedInfo;
  error?: { code: string; message: string; partial: boolean };
};

function Bubble({ m, memNames, onRetry, canRetry }: { m: Message; memNames: Map<string, string>; onRetry?: () => void; canRetry: boolean }) {
  const mine = m.role === "user";
  const note = m.status === "cancelled" ? "Stopped — this reply is incomplete."
    : m.status === "incomplete" ? (m.failure_code === "truncated" ? "Cut off at the length limit — this reply is incomplete." : "Interrupted — this reply is incomplete.")
    : m.status === "failed" ? errText(m.failure_code ?? "interrupted") : m.status === "streaming" ? "Still being written…" : null;
  const used = (m.used_memory_ids ?? []);
  return (
    <li className={`flex ${mine ? "justify-end" : "justify-start"}`}>
      <div className={`max-w-[85%] rounded-[16px] px-4 py-3 text-sm ${mine ? "bg-brand text-on-brand" : "border border-border bg-surface"} ${note ? "border-dashed" : ""}`}>
        <p className="whitespace-pre-wrap break-words">{m.content || (note ? "(no text was produced)" : "")}</p>
        {note && (
          <p className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted">
            <span role="status">{note}</span>
            {canRetry && onRetry && <button onClick={onRetry} className="font-medium text-accent underline underline-offset-4">Try again</button>}
          </p>
        )}
        {!mine && used.length > 0 && (
          <details className="mt-2 text-xs text-muted">
            <summary className="cursor-pointer">Informed by {used.length} approved {used.length === 1 ? "memory" : "memories"}</summary>
            <ul className="mt-1 list-disc pl-4">{used.map((id) => <li key={id}>{memNames.get(id) ?? "A memory that has since been forgotten"}</li>)}</ul>
          </details>
        )}
        {!mine && m.status === "complete" && m.first_token_ms != null && m.duration_ms != null && (
          <p className="mt-2 text-[11px] text-muted">{(m.first_token_ms / 1000).toFixed(1)}s to first word · {(m.duration_ms / 1000).toFixed(1)}s total</p>
        )}
      </div>
    </li>
  );
}

function DeleteDialog({ title, onCancel, onConfirm, busy }: { title: string; onCancel: () => void; onConfirm: (withMemories: boolean) => void; busy: boolean }) {
  const [withMem, setWithMem] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { ref.current?.querySelector<HTMLElement>("button")?.focus(); }, []);
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onCancel();
    addEventListener("keydown", k);
    return () => removeEventListener("keydown", k);
  }, [onCancel]);
  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4" role="dialog" aria-modal="true" aria-labelledby="del-h">
      <button className="absolute inset-0 bg-black/50" aria-label="Cancel" onClick={onCancel} tabIndex={-1} />
      <div ref={ref} className="relative w-full max-w-md rounded-[16px] border border-border bg-surface p-6">
        <h2 id="del-h" className="text-lg font-semibold">Delete “{title}”?</h2>
        <ul className="mt-3 list-disc space-y-1.5 pl-5 text-sm text-muted">
          <li>The messages in this conversation are deleted for good.</li>
          <li>Suggestions from it that you haven’t reviewed are deleted.</li>
          <li>Memories you already approved are kept, because they were your decision — they just lose the quoted messages.</li>
        </ul>
        <label className="mt-4 flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={withMem} onChange={(e) => setWithMem(e.target.checked)} />
          <span>Also delete the memories I approved from this conversation</span></label>
        <div className="mt-6 flex justify-end gap-2">
          <Button variant="secondary" onClick={onCancel}>Keep it</Button>
          <Button variant="danger" loading={busy} onClick={() => onConfirm(withMem)}>Delete conversation</Button>
        </div>
      </div>
    </div>
  );
}

function ReviewBar({ id }: { id: string }) {
  const pref = useLearningPref();
  const rv = useReviewState(id);
  const start = useStartReview();
  const [err, setErr] = useState<string | null>(null);
  const running = rv.data?.state === "running" || start.isPending;
  if (pref.isLoading) return null;
  if (!pref.data?.enabled) {
    return <p className="text-xs text-muted">Learning from conversations is off. <Link to="/app/memories" className="font-medium text-accent underline underline-offset-4">Turn it on in Memories</Link> if you want to review what Madhuora could remember.</p>;
  }
  const n = rv.data?.candidates.length ?? 0;
  return (
    <div className="flex flex-wrap items-center gap-3 text-sm">
      <Button size="sm" variant="secondary" loading={running} disabled={running}
        onClick={() => { setErr(null); start.mutate(id, { onError: (e) => setErr(e instanceof ApiError ? errText(e.code ?? "", e.message) : "Couldn’t start the review.") }); }}>
        Review what Madhuora learned
      </Button>
      {running && <span role="status" className="text-muted">Reading this conversation… this can take a few minutes on a local model.</span>}
      {!running && n > 0 && <Link to="/app/memories" className="font-medium text-accent underline underline-offset-4">{n} {n === 1 ? "idea" : "ideas"} waiting for your review</Link>}
      {!running && n === 0 && rv.data?.reviewed_at && !rv.data.failure_code && <span className="text-muted">Nothing new to remember from this conversation.</span>}
      {!running && rv.data?.failure_code && <span role="alert" className="text-danger">The last review failed ({errText(rv.data.failure_code, "unknown error")}). Your chat is unaffected.</span>}
      {err && <span role="alert" className="text-danger">{err}</span>}
    </div>
  );
}

export function Conversations() {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const status = useChatStatus();
  const convs = useConversations();
  const create = useCreateConversation();
  const del = useDeleteConversation();
  const mems = useMemories();
  const activeId = params.get("c");
  const msgs = useMessages(activeId);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState<Pending | null>(null);
  const [announce, setAnnounce] = useState("");
  const [confirmDel, setConfirmDel] = useState(false);
  const [hint, setHint] = useState(false);
  const ctrl = useRef<AbortController | null>(null);
  const runConv = useRef<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const memNames = useMemo(() => new Map((mems.data ?? []).map((m) => [m.id, m.statement])), [mems.data]);
  const all = msgs.data?.messages ?? [];
  // While a reply for a saved user message is being (re)written, the older failed/incomplete reply is replaced by it.
  const pendingUser = pending ? all.find((m) => m.client_message_id === pending.key) : undefined;
  const messages = pendingUser ? all.filter((m) => !(m.role === "assistant" && m.reply_to === pendingUser.id)) : all;
  const active = convs.data?.find((c) => c.id === activeId);
  const busy = pending?.phase === "waiting" || pending?.phase === "streaming";
  const generating = busy || !!msgs.data?.generating;
  const canChat = status.data?.available === true;

  // Switching conversation drops any stale local state; an in-flight request for another conversation is stopped.
  useEffect(() => () => ctrl.current?.abort(), []);
  useEffect(() => {
    if (runConv.current && runConv.current !== activeId) { ctrl.current?.abort(); runConv.current = null; setPending(null); }
    setHint(false);
  }, [activeId]);
  useEffect(() => { endRef.current?.scrollIntoView?.({ block: "end" }); }, [messages.length, pending?.reply, pending?.phase]);

  const open = (id: string | null) => setParams(id ? { c: id } : {}, { replace: false });

  const run = useCallback(async (cid: string, text: string, key: string) => {
    ctrl.current?.abort();
    const ac = new AbortController();
    ctrl.current = ac;
    runConv.current = cid;
    setHint(false);
    setPending({ key, text, reply: "", phase: "waiting" });
    // After the server has saved the outcome, reload it and only then drop the live bubble, so nothing flickers away.
    const settle = async (alwaysClear: boolean) => {
      await Promise.all([qc.invalidateQueries({ queryKey: K.msgs(cid) }), qc.invalidateQueries({ queryKey: K.convs }), qc.invalidateQueries({ queryKey: K.status })]);
      const saved = qc.getQueryData<{ messages: Message[] }>(K.msgs(cid))?.messages ?? [];
      const user = saved.find((m) => m.client_message_id === key);
      if (alwaysClear || (user && saved.some((m) => m.reply_to === user.id))) setPending((p) => (p && p.key === key ? null : p));
    };
    try {
      const res = await streamMessage(cid, text, key, {
        onStarted: (s) => setPending((p) => (p ? { ...p, started: s } : p)),
        onDelta: (d) => setPending((p) => (p ? { ...p, phase: "streaming", reply: p.reply + d } : p)),
      }, ac.signal);
      if (res.kind === "done") { setHint(res.correctionHint); setAnnounce("Reply complete."); await settle(true); }
      else {
        setAnnounce(`The reply failed. ${errText(res.code, res.message)}`);
        setPending((p) => (p ? { ...p, phase: "failed", error: { code: res.code, message: res.message, partial: res.partial } } : p));
        await settle(false);
      }
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") {
        setAnnounce("Stopped."); // the server saves whatever was written as "stopped"
        await new Promise((r) => setTimeout(r, 400));
        await settle(true);
      } else {
        const code = e instanceof ApiError ? (e.code ?? "interrupted") : e instanceof StreamError ? e.code : "interrupted";
        const message = e instanceof Error ? e.message : "Something went wrong.";
        setPending((p) => (p ? { ...p, phase: "failed", error: { code, message, partial: false } } : p));
        await settle(false);
      }
    }
  }, [qc]);

  const send = async () => {
    const text = draft.trim();
    if (!text || busy || !canChat) return;
    let cid = activeId;
    if (!cid) {
      try { cid = (await create.mutateAsync()).id; } catch { return; }
      setParams({ c: cid }, { replace: true });
    }
    setDraft("");
    void run(cid, text, newKey());
  };

  const stop = () => ctrl.current?.abort();
  const retryPending = () => { if (activeId && pending) void run(activeId, pending.text, pending.key); };
  const retryMessage = (assistant: Message) => {
    const user = messages.find((m) => m.id === assistant.reply_to) ?? [...messages].reverse().find((m) => m.role === "user");
    if (activeId && user?.client_message_id) void run(activeId, user.content, user.client_message_id);
  };
  const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant");
  const max = status.data?.limits.max_user_chars ?? 4000;
  const reason = status.data && !status.data.available ? REASONS[status.data.reason ?? ""] ?? { text: "Chat isn’t available right now." } : null;

  const list = (
    <nav aria-label="Conversations" className="flex flex-col gap-1">
      <Button variant="secondary" size="sm" className="mb-2 justify-start" disabled={create.isPending}
        onClick={() => { open(null); setDraft(""); }}><Icon name="chat" size={16} />New conversation</Button>
      {convs.isLoading && <Skeleton className="h-10" />}
      {convs.data?.length === 0 && <p className="px-1 text-sm text-muted">No conversations yet. Say hello below to start one.</p>}
      {convs.data?.map((c) => (
        <button key={c.id} onClick={() => open(c.id)} aria-current={c.id === activeId ? "page" : undefined}
          className={`truncate rounded-[10px] px-3 py-2 text-left text-sm ${c.id === activeId ? "bg-surface-2 font-medium" : "text-muted hover:bg-surface-2 hover:text-fg"}`}>{c.title}</button>
      ))}
    </nav>
  );

  return (
    <div>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-3xl font-semibold tracking-tight">Conversations</h1>
        {status.data?.is_sample && <Chip>Sample replies — no AI model</Chip>}
      </div>
      {reason && (
        <div className="mt-4"><Notice>{reason.text} {reason.to && <Link to={reason.to} className="font-medium underline underline-offset-4">{reason.label}</Link>}</Notice></div>
      )}
      {status.data?.available && status.data.profile_outdated && (
        <div className="mt-4"><Notice>Your description changed after the last interpretation, so replies still use the older one. <Link to="/app/studio" className="font-medium underline underline-offset-4">Update it in Twin Studio</Link>.</Notice></div>
      )}
      {status.data?.available && status.data.model_busy && !busy && (
        <div className="mt-4"><Notice>The local model is busy with another job (for example understanding the character). A new reply will wait for it to finish — try again in a moment.</Notice></div>
      )}

      <div className="mt-6 grid gap-6 md:grid-cols-[220px_1fr]">
        <div className={`${activeId ? "hidden md:block" : ""}`}>{list}</div>
        <section className="min-w-0" aria-label="Conversation">
          {activeId && (
            <div className="mb-3 flex items-center justify-between gap-2">
              <button className="md:hidden text-sm font-medium text-accent" onClick={() => open(null)}>← All conversations</button>
              <h2 className="hidden min-w-0 truncate text-lg font-semibold md:block">{active?.title ?? "Conversation"}</h2>
              <Button variant="ghost" size="sm" onClick={() => setConfirmDel(true)} disabled={generating} aria-label="Delete conversation"><Icon name="trash" size={16} /><span className="hidden sm:inline">Delete</span></Button>
            </div>
          )}

          <div className="min-h-[40vh] rounded-[16px] border border-border bg-surface p-4">
            {!activeId && !pending && <p className="py-12 text-center text-sm text-muted">Start a conversation. Replies appear word by word as the model writes them.</p>}
            {msgs.isLoading && activeId && <Skeleton className="h-24" />}
            {msgs.isError && <Notice tone="error">Couldn’t load this conversation. {msgs.error instanceof ApiError && msgs.error.status === 404 ? "It may have been deleted." : ""}</Notice>}
            <ol className="flex flex-col gap-3" aria-label="Chat history">
              {messages.map((m) => (
                <Bubble key={m.id} m={m} memNames={memNames} canRetry={m.id === lastAssistant?.id && m.status !== "complete" && m.status !== "streaming" && !busy && canChat}
                  onRetry={() => retryMessage(m)} />
              ))}
              {pending && !pendingUser && (
                <li className="flex justify-end"><div className="max-w-[85%] whitespace-pre-wrap break-words rounded-[16px] bg-brand px-4 py-3 text-sm text-on-brand">{pending.text}</div></li>
              )}
              {pending && (
                <li className="flex justify-start" data-testid="live-reply">
                  <div className={`max-w-[85%] rounded-[16px] border px-4 py-3 text-sm ${pending.phase === "failed" ? "border-dashed border-danger/60" : "border-border"} bg-surface`}>
                    {pending.phase === "waiting" && (
                      <p className="flex items-center gap-2 text-muted"><span className="size-3 motion-safe:animate-spin rounded-full border-2 border-current border-t-transparent" aria-hidden />
                        {pending.started?.replayed ? "Fetching the saved reply…" : "Waiting for the first words — a local model can take a minute."}</p>
                    )}
                    {pending.reply && <p className="whitespace-pre-wrap break-words" aria-live="off">{pending.reply}</p>}
                    {pending.phase === "failed" && pending.error && (
                      <div className="mt-2 text-xs">
                        <p role="alert" className="text-danger">{errText(pending.error.code, pending.error.message)}{pending.reply ? " What was written is kept and marked incomplete." : ""}</p>
                        {canChat && <button onClick={retryPending} className="mt-1 font-medium text-accent underline underline-offset-4">Try again</button>}
                      </div>
                    )}
                    {pending.started && pending.started.memories_used.length > 0 && (
                      <details className="mt-2 text-xs text-muted"><summary className="cursor-pointer">Informed by {pending.started.memories_used.length} approved {pending.started.memories_used.length === 1 ? "memory" : "memories"}</summary>
                        <ul className="mt-1 list-disc pl-4">{pending.started.memories_used.map((m) => <li key={m.id}>{m.statement}</li>)}</ul></details>
                    )}
                  </div>
                </li>
              )}
              {!busy && msgs.data?.generating && <li className="text-xs text-muted" role="status">A reply is still being written (started elsewhere)…</li>}
            </ol>
            <div ref={endRef} />
          </div>

          {pending?.started?.context.trimmed && (
            <p className="mt-2 text-xs text-muted">This conversation is long, so the reply was based on the latest {pending.started.context.earlier_messages_used} of {pending.started.context.total} earlier messages.</p>
          )}
          {hint && <p className="mt-2 text-xs text-muted">That sounded like a correction. If you’d like Madhuora to remember it, use “Review what Madhuora learned” — nothing is saved until you approve it.</p>}
          <p className="sr-only" role="status" aria-live="polite">{announce}</p>

          <form className="mt-3" onSubmit={(e) => { e.preventDefault(); void send(); }}>
            <label htmlFor="composer" className="sr-only">Message</label>
            <textarea id="composer" value={draft} onChange={(e) => setDraft(e.target.value)} rows={3} maxLength={max} disabled={!canChat}
              placeholder={canChat ? "Write a message…" : "Chat isn’t available yet"} aria-describedby="composer-help"
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(); } }}
              className="w-full rounded-[12px] border border-border bg-surface-2 px-3 py-2 text-sm placeholder:text-muted/70 focus:border-ring disabled:opacity-60" />
            <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
              <span id="composer-help" className="text-xs text-muted">Enter to send · Shift+Enter for a new line · {draft.length}/{max}</span>
              {busy ? <Button type="button" variant="secondary" onClick={stop}>Stop</Button>
                : <Button type="submit" disabled={!draft.trim() || !canChat || generating} loading={create.isPending}>Send</Button>}
            </div>
          </form>
          {activeId && <div className="mt-6 border-t border-border pt-4"><ReviewBar id={activeId} /></div>}
        </section>
      </div>
      {confirmDel && active && (
        <DeleteDialog title={active.title} busy={del.isPending} onCancel={() => setConfirmDel(false)}
          onConfirm={(withMemories) => del.mutate({ id: active.id, deleteMemories: withMemories }, { onSuccess: () => { setConfirmDel(false); open(null); } })} />
      )}
    </div>
  );
}
