import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, type CharacterState, type ProviderInfo, type Twin } from "../lib/api";
import { useAnalyzeCharacter, useCompleteStep, useReady, useSaveCharacter } from "../hooks/useMe";
import { CharacterProfileView } from "./CharacterProfileView";
import { Button, Notice, TextArea } from "./ui";

export const MAX_CHARS = 8000;

const PLACEHOLDER =
  "For example: “Meera is the one who remembers everyone’s birthdays. She teases her closest friends " +
  "constantly but goes quiet and careful around people she has just met. She never says ‘I love you’ " +
  "out loud; she shows it by turning up with food. When someone is upset she listens first, then " +
  "tells them plainly what she thinks…”";

const IDEAS = [
  "Everyday personality", "Interests and habits", "Sense of humour", "Values and what drives them",
  "Relationships", "How they react when upset", "How they speak, and phrases they use", "Mannerisms",
  "Preferences and boundaries", "How they differ with friends, family, strangers",
];

const STATUS: Record<CharacterState["status"], string> = {
  empty: "Not started",
  not_analysed: "Not analysed yet",
  current: "Up to date with your description",
  outdated: "Your description has changed since this was made",
};

type Props = {
  twin: Twin;
  character: CharacterState;
  consentGranted: boolean;
  provider: ProviderInfo;
  mode: "studio" | "onboarding";
  onDirtyChange?: (dirty: boolean) => void;
  onContinue?: () => void;
  onSkip?: () => void;
};

export function CharacterEditor({ twin, character, consentGranted, provider, mode, onDirtyChange, onContinue, onSkip }: Props) {
  const baseline = twin.character_description;
  const [text, setText] = useState(baseline);
  const save = useSaveCharacter();
  const analyze = useAnalyzeCharacter();
  const complete = useCompleteStep();
  const ready = useReady();
  const [err, setErr] = useState<ApiError | Error | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const analysing = useRef(false);

  const trimmed = text.trim();
  const dirty = trimmed !== baseline.trim();
  const over = text.length - MAX_CHARS;
  const tooShort = trimmed.length < character.min_chars;
  useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange]);

  const aiOff = ready.data?.configured?.ai === false;
  const running = character.analysis?.state === "running";
  const busy = save.isPending || analyze.isPending || complete.isPending || running;
  const elapsed = useElapsed(running ? character.analysis?.started_at ?? null : null);

  // After this page started an analysis, say once when it has finished successfully. (A failure is shown from
  // `character.failure`.) Works for a 2-second job and for a 5-minute one, because it waits for the server's own state.
  const started = useRef(false);
  useEffect(() => {
    if (!started.current || running || analyze.isPending) return;
    started.current = false;
    if (character.status === "current" && !character.failure) setNote("Interpretation updated.");
  }, [running, analyze.isPending, character.status, character.failure]);

  // Persist first; returns the version that was actually saved so analysis can't read a stale one.
  const persist = async (): Promise<number> => {
    if (!dirty) return character.description_version;
    const r = await save.mutateAsync({ description: trimmed, baseVersion: character.description_version });
    return r.character.description_version;
  };

  const run = async (fn: () => Promise<void>) => {
    setErr(null);
    setNote(null);
    try { await fn(); } catch (e) { setErr(e instanceof Error ? e : new Error("Something went wrong.")); }
  };

  const onSave = () => run(async () => { await persist(); setNote("Saved."); });

  const onAnalyze = () => run(async () => {
    if (analysing.current) return; // guards double-clicks before React re-renders
    analysing.current = true;
    try {
      const v = await persist();
      const r = await analyze.mutateAsync(v);
      if (r.cached) setNote("Nothing has changed since the last interpretation.");
      else started.current = true;
    } finally { analysing.current = false; }
  });

  const onContinueClick = () => run(async () => {
    await persist();
    await complete.mutateAsync("personality");
    onContinue?.();
  });

  const analyseDisabled =
    busy || tooShort || over > 0 || !consentGranted || aiOff || (character.status === "current" && !dirty);
  const why =
    !consentGranted ? `AI processing consent is needed before Madhuora can read this. Agree to the current provider (${providerName(provider.id)}) in Settings; an agreement made for another provider doesn’t carry over.`
    : aiOff ? "AI analysis isn’t set up on this server yet. Your description is still saved."
    : tooShort ? `Write at least ${character.min_chars} characters so there is something to interpret.`
    : null;

  const status = dirty ? "You have unsaved changes" : STATUS[character.status];
  const failureNote = character.failure && !dirty && consentGranted && !running ? failureText(character.failure) : null;

  return (
    <div>
      <div>
        <h2 className="text-xl font-semibold">Character</h2>
        <p className="mt-1 max-w-[62ch] text-sm text-muted">
          Tell Madhuora who they are, in your own words. Their personality, the little things they care about,
          how they express themselves, and how they respond to the people around them.
        </p>
      </div>

      <div className="mt-6">
        <TextArea
          label="Describe the person"
          value={text}
          onChange={(e) => { setText(e.target.value); setNote(null); }}
          placeholder={PLACEHOLDER}
          fieldClassName="min-h-[320px] text-base leading-relaxed"
          error={over > 0 ? `That’s ${over} characters over the ${MAX_CHARS.toLocaleString()} limit. Please shorten it.` : null}
          hint={`${text.length.toLocaleString()} / ${MAX_CHARS.toLocaleString()} characters`}
        />
        <details className="mt-3 text-sm text-muted">
          <summary className="cursor-pointer select-none py-1">Things you might mention (none are required)</summary>
          <ul className="mt-2 grid gap-x-6 gap-y-1 sm:grid-cols-2">{IDEAS.map((i) => <li key={i}>{i}</li>)}</ul>
        </details>
      </div>

      <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
        <p role="status" aria-live="polite" className="text-sm text-muted">
          {analyze.isPending || running
            ? `${provider.id === "ollama" ? "Reading your description with the local model" : "Reading your description"}… ${elapsed ? `${elapsed} so far. ` : ""}${provider.id === "ollama" ? "A local model can take several minutes; you can leave this page and the result will still be saved." : ""}`
            : save.isPending ? "Saving…" : note ?? status}
        </p>
        <div className="flex flex-wrap gap-2">
          {mode === "studio" && (
            <Button variant="secondary" disabled={!dirty || over > 0 || busy} loading={save.isPending} onClick={onSave}>
              Save description
            </Button>
          )}
          <Button disabled={analyseDisabled} loading={analyze.isPending || running} onClick={onAnalyze}>
            {character.profile ? "Update the interpretation" : "Understand this character"}
          </Button>
        </div>
      </div>

      {provider.external && provider.development_only && (
        <div className="mt-4"><Notice>
          <strong>Development AI provider ({provider.label}).</strong> Understanding a character sends your description
          to a free test service. Use fictional or non-sensitive text only while this is active.
        </Notice></div>
      )}
      {provider.id === "ollama" && provider.local && (
        <p className="mt-4 text-sm text-muted">
          Analysed by a model running on this computer (Ollama). Your account and saved text still use Madhuora’s online
          services; <Link className="underline" to="/app/settings">Settings</Link> explains what stays local.
        </p>
      )}
      {why && <p className="mt-3 text-sm text-muted">{why}{!consentGranted && <> <Link className="underline" to="/app/settings">Open Settings</Link>.</>}</p>}
      {err && <div className="mt-4"><Notice tone="error">{err.message}{" "}
        {err instanceof ApiError && err.code === "consent_required" && <Link className="underline" to="/app/settings">Open Settings</Link>}
        {err instanceof ApiError && err.status !== 409 && err.status !== 403 && err.status !== 422 && !aiOff && <span className="text-muted"> Your description is saved. You can retry.</span>}
      </Notice></div>}
      {!err && failureNote && <div className="mt-4"><Notice tone="error">{failureNote}</Notice></div>}

      {mode === "onboarding" && (
        <div className="mt-8 flex flex-wrap justify-end gap-3">
          <Button variant="ghost" disabled={busy} onClick={onSkip}>Skip for now</Button>
          <Button size="lg" loading={complete.isPending || save.isPending} disabled={busy || over > 0 || !trimmed} onClick={onContinueClick}>
            Save and continue
          </Button>
        </div>
      )}

      {character.profile && (
        <div className="mt-12">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-lg font-semibold">What Madhuora understood</h3>
            <span className="text-sm text-muted">{STATUS[dirty && character.status === "current" ? "outdated" : character.status]}</span>
          </div>
          {character.generated_by?.is_sample ? (
            <div className="mt-3"><Notice>
              <strong>Sample output, not an AI reading.</strong> This server is in sample mode, so no AI model read
              your description. The text below is a fixed example of how an interpretation will look.
            </Notice></div>
          ) : (
            <p className="mt-1 max-w-[62ch] text-sm text-muted">
              An AI-generated interpretation of your words{character.generated_by?.provider ? <>, made by {providerName(character.generated_by.provider)}{character.generated_by.model ? <> ({character.generated_by.model})</> : null}</> : null}.
              It can be wrong or incomplete. Your own description above stays the source of truth and is never replaced by this.
              {character.generated_at && <> Generated {new Date(character.generated_at).toLocaleString()}.</>}
            </p>
          )}
          {(character.status === "outdated" || (dirty && character.status === "current")) && (
            <div className="mt-4"><Notice>
              This was made from an earlier version of your description, so it may not reflect your latest changes.
              Choose “Update the interpretation” to refresh it.
            </Notice></div>
          )}
          <div className="mt-6"><CharacterProfileView profile={character.profile} /></div>
        </div>
      )}
    </div>
  );
}

/** Seconds since `startedAt` as "1m 05s", re-read every second. Real elapsed time only; never a fake progress bar. */
function useElapsed(startedAt: string | null): string | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!startedAt) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [startedAt]);
  if (!startedAt) return null;
  const secs = Math.max(0, Math.round((now - Date.parse(startedAt)) / 1000));
  return secs < 60 ? `${secs}s` : `${Math.floor(secs / 60)}m ${String(secs % 60).padStart(2, "0")}s`;
}

const providerName = (p: string) => ({ nvidia: "NVIDIA", ollama: "Ollama (local model)", openai: "OpenAI", mock: "the sample generator" } as Record<string, string>)[p] ?? p;

function failureText(code: string): string {
  const base = "The last attempt to analyse this didn’t work";
  const m: Record<string, string> = {
    timeout: `${base}: the AI took too long. Your previous interpretation is unchanged.`,
    rate_limited: `${base}: the AI service was busy. Try again shortly.`,
    malformed_response: `${base}: the AI’s reply couldn’t be read. Try again.`,
    empty_response: `${base}: the model sent back an empty answer. Try again; if it keeps happening the model or its reasoning setting needs checking by whoever runs the server.`,
    not_json: `${base}: the model didn’t reply in the required format (it wasn’t valid JSON). Try again. Your previous interpretation is unchanged.`,
    schema_invalid: `${base}: the model’s reply didn’t match the required structure. Try again. Your previous interpretation is unchanged.`,
    truncated: `${base}: the answer was cut off. Try again.`,
    refused: `${base}: the AI declined this description.`,
    quality_failed: `${base}: the interpretation didn’t match your description closely enough to be saved. Your previous interpretation is unchanged. You can try again.`,
    quota_exhausted: `${base}: the free AI allowance is used up for now. Your description and previous interpretation are unchanged.`,
    provider_auth: `${base}: the AI service rejected the server’s credentials. This needs fixing by whoever runs the server.`,
    provider_unreachable: `${base}: the AI service couldn’t be reached. Your previous interpretation is unchanged.`,
    provider_rejected: `${base}: the AI service rejected the request. This needs fixing by whoever runs the server.`,
    local_unavailable: `${base}: Ollama isn’t running on this computer, or couldn’t be reached. Start it and try again. Your previous interpretation is unchanged.`,
    local_model_missing: `${base}: the configured Ollama model isn’t installed on this computer. This needs fixing by whoever runs the server. Your previous interpretation is unchanged.`,
    context_too_small: `${base}: the local model’s context window is too small for this description, so nothing was saved. Your previous interpretation is unchanged.`,
  };
  return m[code] ?? `${base}. Your previous interpretation is unchanged. You can retry.`;
}
