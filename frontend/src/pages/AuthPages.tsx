import { useEffect, useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { Logo } from "../components/Logo";
import { Button, Notice, TextField } from "../components/ui";
import { isConfigured } from "../lib/config";
import { supabase } from "../lib/supabase";

type Mode = "signin" | "signup" | "magic" | "reset";
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const redirect = () => `${location.origin}/auth/callback`;

function Frame({ title, sub, children }: { title: string; sub: string; children: React.ReactNode }) {
  return (
    <div className="grid min-h-screen md:grid-cols-[1fr_1.1fr]">
      <div className="atelier-bg" aria-hidden />
      <aside className="hidden flex-col justify-between bg-maroon p-12 text-[#faf5ed] md:flex">
        <Link to="/" aria-label="Madhuora home"><Logo variant="gold-on-maroon" height={34} padded={false} /></Link>
        <div>
          <p className="max-w-sm text-4xl font-semibold leading-tight tracking-tight text-gold">What matters, carried forward.</p>
          <p className="mt-5 max-w-sm text-sm text-[#faf5ed]/80">A personal AI twin — clearly an AI, shaped by you, with your consent at every step.</p>
        </div>
        <p className="text-xs text-[#faf5ed]/70">Named for Madhu Sharma, the founder’s grandmother.</p>
      </aside>
      <main className="flex items-center justify-center px-5 py-12">
        <div className="w-full max-w-sm">
          <div className="mb-8 md:hidden"><Link to="/" aria-label="Madhuora home"><Logo variant="gold-on-maroon" height={26} /></Link></div>
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          <p className="mt-1.5 text-sm text-muted">{sub}</p>
          <div className="mt-6">{children}</div>
        </div>
      </main>
    </div>
  );
}

export function AuthPage({ initial }: { initial: Mode }) {
  const { session } = useAuth();
  const loc = useLocation();
  const [mode, setMode] = useState<Mode>(initial);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const [touched, setTouched] = useState(false);
  useEffect(() => { setMode(initial); setSent(false); setErr(null); }, [initial]);

  if (session) return <Navigate to={(loc.state as { from?: string } | null)?.from ?? "/app"} replace />;

  const emailErr = touched && !EMAIL_RE.test(email) ? "Enter a valid email address." : null;
  const pwErr = touched && mode !== "magic" && mode !== "reset" && password.length < (mode === "signup" ? 10 : 1)
    ? (mode === "signup" ? "Use at least 10 characters." : "Enter your password.") : null;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    setErr(null);
    if (!EMAIL_RE.test(email) || pwErr || (mode === "signup" && password.length < 10) || (mode === "signin" && !password)) return;
    setBusy(true);
    try {
      if (mode === "signin") {
        const { error } = await supabase.auth.signInWithPassword({ email, password });
        if (error) setErr(error.status === 429 ? "Too many attempts. Please wait a moment and try again." : "That email and password don’t match.");
      } else if (mode === "signup") {
        const { error } = await supabase.auth.signUp({ email, password, options: { emailRedirectTo: redirect() } });
        if (error && error.status === 429) setErr("Too many attempts. Please wait a moment and try again.");
        else if (error && error.status !== 400 && error.status !== 422) setErr("We couldn’t create the account right now. Please try again.");
        else setSent(true); // identical outcome whether or not the address is already registered
      } else if (mode === "magic") {
        const { error } = await supabase.auth.signInWithOtp({ email, options: { emailRedirectTo: redirect(), shouldCreateUser: true } });
        if (error?.status === 429) setErr("Too many attempts. Please wait a moment and try again."); else setSent(true);
      } else {
        const { error } = await supabase.auth.resetPasswordForEmail(email, { redirectTo: redirect() });
        if (error?.status === 429) setErr("Too many attempts. Please wait a moment and try again."); else setSent(true);
      }
    } catch {
      setErr(navigator.onLine ? "Couldn’t reach the service. Please try again." : "You appear to be offline.");
    } finally { setBusy(false); }
  };

  const copy: Record<Mode, [string, string]> = {
    signin: ["Welcome back", "Sign in to continue with your twin."],
    signup: ["Create your account", "Start by creating a private account."],
    magic: ["Email me a link", "We’ll send a one-time sign-in link."],
    reset: ["Reset your password", "We’ll email you a link to choose a new one."],
  };

  return (
    <Frame title={copy[mode][0]} sub={copy[mode][1]}>
      {!isConfigured && <div className="mb-4"><Notice tone="error">This app isn’t connected to its backend yet. Add your Supabase values to <code>frontend/.env.local</code>.</Notice></div>}
      {sent ? (
        <div className="space-y-4">
          <Notice tone="success">If that address can be used, an email is on its way. Check your inbox (and spam folder) and follow the link.</Notice>
          <button className="text-sm underline" onClick={() => setSent(false)}>Use a different email</button>
        </div>
      ) : (
        <form onSubmit={submit} noValidate className="space-y-4">
          <TextField label="Email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} error={emailErr} />
          {(mode === "signin" || mode === "signup") && (
            <TextField label="Password" type="password" autoComplete={mode === "signup" ? "new-password" : "current-password"}
              value={password} onChange={(e) => setPassword(e.target.value)} error={pwErr} hint={mode === "signup" ? "At least 10 characters." : undefined} />
          )}
          {err && <Notice tone="error">{err}</Notice>}
          <Button type="submit" size="lg" className="w-full" loading={busy} disabled={!isConfigured}>
            {{ signin: "Sign in", signup: "Create account", magic: "Send link", reset: "Send reset link" }[mode]}
          </Button>
        </form>
      )}
      <div className="mt-6 space-y-2 text-sm text-muted">
        {mode === "signin" && (<>
          <p>New here? <Link className="font-medium text-fg underline underline-offset-4" to="/register">Create an account</Link></p>
          <p><button className="underline underline-offset-4" onClick={() => { setMode("magic"); setSent(false); }}>Email me a sign-in link</button> · <button className="underline underline-offset-4" onClick={() => { setMode("reset"); setSent(false); }}>Forgot password?</button></p>
        </>)}
        {mode !== "signin" && <p>Have an account? <Link className="font-medium text-fg underline underline-offset-4" to="/login" onClick={() => setSent(false)}>Sign in</Link></p>}
      </div>
    </Frame>
  );
}

export function AuthCallback() {
  const nav = useNavigate();
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const { data } = supabase.auth.onAuthStateChange((event) => {
      if (event === "PASSWORD_RECOVERY") nav("/reset-password", { replace: true });
      else if (event === "SIGNED_IN") nav("/app", { replace: true });
    });
    const t = setTimeout(() => setFailed(true), 10000);
    return () => { data.subscription.unsubscribe(); clearTimeout(t); };
  }, [nav]);
  return (
    <Frame title={failed ? "That link didn’t work" : "Signing you in…"} sub={failed ? "It may have expired or already been used." : "One moment."}>
      {failed && <Link to="/login"><Button>Back to sign in</Button></Link>}
    </Frame>
  );
}

export function ResetPassword() {
  const nav = useNavigate();
  const { session, loading } = useAuth();
  const [pw, setPw] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (!loading && !session) return <Navigate to="/login" replace />;
  const go = async (e: FormEvent) => {
    e.preventDefault();
    if (pw.length < 10) return setErr("Use at least 10 characters.");
    setBusy(true); setErr(null);
    const { error } = await supabase.auth.updateUser({ password: pw });
    setBusy(false);
    if (error) setErr("We couldn’t update your password. The link may have expired."); else nav("/app", { replace: true });
  };
  return (
    <Frame title="Choose a new password" sub="Use something you don’t use anywhere else.">
      <form onSubmit={go} className="space-y-4">
        <TextField label="New password" type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} hint="At least 10 characters." />
        {err && <Notice tone="error">{err}</Notice>}
        <Button type="submit" size="lg" className="w-full" loading={busy}>Update password</Button>
      </form>
    </Frame>
  );
}
