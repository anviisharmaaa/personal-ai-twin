import { useState } from "react";
import { Button, Card, Chip, Notice, Skeleton, TextField } from "../components/ui";
import { useAuth } from "../auth/AuthProvider";
import { useTheme, type ThemePref } from "../hooks/useTheme";
import { useGrantConsent, useMe, useSaveProfile, useWithdrawConsent } from "../hooks/useMe";
import { supabase } from "../lib/supabase";
import { fromRecord, sameValue, toPayload, UserIdentityFields, type UserIdentityValue } from "../components/UserIdentityFields";

const zones = (): string[] => {
  try { return (Intl as unknown as { supportedValuesOf: (k: string) => string[] }).supportedValuesOf("timeZone"); } catch { return ["UTC"]; }
};

export function Settings() {
  const me = useMe();
  const { session, signOut } = useAuth();
  const { pref, set } = useTheme();
  if (me.isLoading) return <div className="space-y-4"><Skeleton className="h-10 w-48" /><Skeleton className="h-48" /></div>;
  if (me.isError || !me.data) return <Notice tone="error">We couldn’t load your settings. <button className="underline" onClick={() => me.refetch()}>Try again</button></Notice>;
  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-semibold tracking-tight">Settings</h1>
      <ProfileCard />
      <AboutYouCard />
      <Card>
        <h2 className="text-base font-semibold">Theme</h2>
        <div role="radiogroup" aria-label="Theme" className="mt-4 inline-flex gap-1 rounded-[10px] border border-border bg-surface-2 p-1">
          {(["system", "light", "dark"] as ThemePref[]).map((t) => (
            <button key={t} role="radio" aria-checked={pref === t} onClick={() => set(t)}
              className={`h-9 rounded-[6px] px-4 text-sm capitalize ${pref === t ? "bg-brand text-on-brand" : "text-muted hover:text-fg"}`}>{t}</button>
          ))}
        </div>
      </Card>
      <ConsentCard />
      <PasswordCard email={session?.user.email ?? ""} />
      <Card>
        <h2 className="text-base font-semibold">Security & your data</h2>
        <ul className="mt-4 space-y-3 text-sm">
          <li className="flex items-center justify-between gap-3"><span>Two-factor authentication (authenticator app)</span><Chip tone="soon">Not available yet</Chip></li>
          <li className="flex items-center justify-between gap-3"><span>Export your data</span><Chip tone="soon">Not available yet</Chip></li>
          <li className="flex items-center justify-between gap-3"><span>Delete your account</span><Chip tone="soon">Not available yet</Chip></li>
        </ul>
        <p className="mt-4 text-sm text-muted">We won’t show export or deletion buttons until they actually work. If you need your data removed before then, contact the Madhuora team.</p>
      </Card>
      <Card><h2 className="text-base font-semibold">Session</h2><div className="mt-4"><Button variant="secondary" onClick={signOut}>Sign out</Button></div></Card>
    </div>
  );
}

function ProfileCard() {
  const me = useMe();
  const save = useSaveProfile();
  const [name, setName] = useState(me.data?.profile?.display_name ?? "");
  const [tz, setTz] = useState(me.data?.profile?.timezone ?? "UTC");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const go = async () => {
    setMsg(null);
    try { await save.mutateAsync({ display_name: name.trim(), timezone: tz }); setMsg({ ok: true, text: "Saved." }); }
    catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Couldn’t save." }); }
  };
  return (
    <Card>
      <h2 className="text-base font-semibold">Profile</h2>
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <TextField label="Display name" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} />
        <div>
          <label htmlFor="tz" className="mb-1.5 block text-sm font-medium">Time zone</label>
          <select id="tz" value={tz} onChange={(e) => setTz(e.target.value)} className="h-10 w-full rounded-[10px] border border-border bg-surface-2 px-3 text-sm">
            {[...new Set([tz, Intl.DateTimeFormat().resolvedOptions().timeZone, ...zones()])].map((z) => <option key={z}>{z}</option>)}
          </select>
        </div>
      </div>
      <div className="mt-4 flex items-center gap-3">
        <Button onClick={go} loading={save.isPending}>Save profile</Button>
        {msg && <span role="status" className={`text-sm ${msg.ok ? "text-success" : "text-danger"}`}>{msg.text}</span>}
      </div>
    </Card>
  );
}

function AboutYouCard() {
  const me = useMe();
  const save = useSaveProfile();
  const saved = fromRecord(me.data?.profile);
  const [v, setV] = useState<UserIdentityValue>(saved);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const go = async () => {
    setMsg(null);
    try { await save.mutateAsync(toPayload(v)); setMsg({ ok: true, text: "Saved." }); }
    catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Couldn’t save." }); }
  };
  return (
    <Card>
      <h2 className="text-base font-semibold">About you</h2>
      <p className="mt-1 text-sm text-muted">
        Optional. Helps characters address you naturally (for example the right Hindi verb endings). It belongs to your account,
        is never taken from your name or messages, and is separate from your characters’ own gender.
      </p>
      <div className="mt-4"><UserIdentityFields value={v} onChange={(n) => { setMsg(null); setV(n); }} /></div>
      <div className="mt-4 flex items-center gap-3">
        <Button onClick={go} loading={save.isPending} disabled={sameValue(v, saved)}>Save</Button>
        {msg && <span role="status" className={`text-sm ${msg.ok ? "text-success" : "text-danger"}`}>{msg.text}</span>}
      </div>
    </Card>
  );
}

function ConsentCard() {
  const me = useMe();
  const withdraw = useWithdrawConsent();
  const c = me.data!.ai_consent;
  const grant = useGrantConsent(c.current_version);
  const [err, setErr] = useState<string | null>(null);
  return (
    <Card>
      <h2 className="text-base font-semibold">AI processing consent</h2>
      <p className="mt-2 text-sm text-muted">
        {c.granted ? `You agreed to external AI processing (v${c.version}). You can withdraw at any time.`
          : c.version ? "The wording or the AI provider changed since you last agreed, or you withdrew consent. No AI feature will run until you agree again."
          : "You haven’t agreed to external AI processing, so no AI features can run for your twin."}
      </p>
      <div className="mt-3 text-sm">
        <p className="font-medium">AI provider on this server: {c.provider.label}</p>
        <ul className="mt-2 list-disc space-y-2 pl-5 text-muted">
          {c.provider.disclosure.map((d) => <li key={d}>{d}</li>)}
        </ul>
        {c.provider.external && <p className="mt-2 text-muted">Nothing is sent until you ask Madhuora to understand a character.</p>}
      </div>
      {!c.granted && <div className="mt-4"><Button loading={grant.isPending} onClick={async () => { setErr(null); try { await grant.mutateAsync(); } catch (e) { setErr(e instanceof Error ? e.message : "Couldn’t record consent."); } }}>Agree to AI processing</Button></div>}
      {c.granted && <div className="mt-4"><Button variant="secondary" loading={withdraw.isPending} onClick={async () => { setErr(null); try { await withdraw.mutateAsync(); } catch (e) { setErr(e instanceof Error ? e.message : "Couldn’t withdraw."); } }}>Withdraw consent</Button></div>}
      {err && <div className="mt-3"><Notice tone="error">{err}</Notice></div>}
    </Card>
  );
}

function PasswordCard({ email }: { email: string }) {
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const go = async () => {
    setMsg(null);
    if (next.length < 10) return setMsg({ ok: false, text: "Use at least 10 characters." });
    setBusy(true);
    // Sensitive action: re-verify the current password first.
    const re = await supabase.auth.signInWithPassword({ email, password: cur });
    if (re.error) { setBusy(false); return setMsg({ ok: false, text: "Your current password isn’t right." }); }
    const { error } = await supabase.auth.updateUser({ password: next });
    setBusy(false);
    if (error) return setMsg({ ok: false, text: "Couldn’t change the password. Please try again." });
    setCur(""); setNext(""); setMsg({ ok: true, text: "Password changed." });
  };
  return (
    <Card>
      <h2 className="text-base font-semibold">Password</h2>
      <p className="mt-1 text-sm text-muted">Signed in as {email}. If you use email links only, set a password by using “Forgot password” on the sign-in page.</p>
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <TextField label="Current password" type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} />
        <TextField label="New password" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} hint="At least 10 characters." />
      </div>
      <div className="mt-4 flex items-center gap-3">
        <Button onClick={go} loading={busy} disabled={!cur || !next}>Change password</Button>
        {msg && <span role="status" className={`text-sm ${msg.ok ? "text-success" : "text-danger"}`}>{msg.text}</span>}
      </div>
    </Card>
  );
}
