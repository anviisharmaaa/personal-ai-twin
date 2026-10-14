import { Link } from "react-router-dom";
import { motion, useReducedMotion } from "motion/react";
import { Logo } from "../components/Logo";
import { Button, Chip } from "../components/ui";
import { useAuth } from "../auth/AuthProvider";

const FEATURES: { title: string; body: string; status: "Available" | "Coming next" | "Planned" }[] = [
  { title: "Your twin’s identity & character", body: "Name your twin, then describe their character in your own words. Madhuora reads it and shows you its interpretation.", status: "Available" },
  { title: "Portrait", body: "Add a still portrait, stored privately. Framing, backdrop and lighting only — never altered faces.", status: "Available" },
  { title: "Text conversations", body: "Talk with your twin; replies stream in as they’re written.", status: "Coming next" },
  { title: "Memories you approve", body: "Stories and facts your twin can draw on — only after you say yes.", status: "Coming next" },
  { title: "Voice messages", body: "Send a voice note, review the transcript, hear a reply.", status: "Planned" },
  { title: "Gentle scheduled messages", body: "Check-ins you control, with quiet hours and limits.", status: "Planned" },
];

export function Landing() {
  const { session } = useAuth();
  const reduce = useReducedMotion();
  const fade = (d: number) => (reduce ? {} : { initial: { opacity: 0, y: 16 }, animate: { opacity: 1, y: 0 }, transition: { duration: 0.5, delay: d, ease: "easeOut" as const } });
  return (
    <div className="min-h-screen">
      <div className="atelier-bg" aria-hidden />
      <header className="mx-auto flex max-w-6xl items-center justify-between px-5 py-5">
        <Logo variant="gold-on-maroon" height={26} />
        <nav className="flex items-center gap-2" aria-label="Account">
          {session ? <Link to="/app"><Button>Open app</Button></Link> : (<>
            <Link to="/login"><Button variant="ghost">Sign in</Button></Link>
            <Link to="/register"><Button>Get started</Button></Link>
          </>)}
        </nav>
      </header>

      <main>
        <section className="relative mx-auto max-w-6xl px-5 pb-20 pt-16 md:pt-28">
          <svg aria-hidden viewBox="0 0 600 600" className="pointer-events-none absolute -right-24 top-0 hidden w-[540px] opacity-60 md:block" fill="none" stroke="currentColor">
            {[120, 190, 260].map((r, i) => (
              <motion.path key={r} d={`M ${300 - r} 460 A ${r} ${r} 0 0 1 ${300 + r} 460`} strokeWidth="1.2" className="text-accent"
                initial={reduce ? false : { pathLength: 0, opacity: 0 }} animate={{ pathLength: 1, opacity: 0.55 - i * 0.12 }} transition={{ duration: 1.6, delay: 0.3 + i * 0.25, ease: "easeInOut" }} />
            ))}
            <circle cx="300" cy="170" r="34" className="fill-accent/80 stroke-none" />
            <circle cx="415" cy="235" r="20" className="fill-accent/55 stroke-none" />
          </svg>
          <motion.p {...fade(0)} className="text-sm font-medium uppercase tracking-[0.2em] text-muted">Madhuora</motion.p>
          <motion.h1 {...fade(0.1)} className="mt-5 max-w-3xl text-5xl font-semibold leading-[1.05] tracking-tight md:text-7xl">What matters, carried forward.</motion.h1>
          <motion.p {...fade(0.2)} className="mt-6 max-w-xl text-lg text-muted">
            Create a personal AI twin shaped by your stories, humour and values. It is always clearly an AI — never you, never a replacement — and you decide what it knows.
          </motion.p>
          <motion.div {...fade(0.3)} className="mt-9 flex flex-wrap gap-3">
            <Link to="/register"><Button size="lg">Create your twin</Button></Link>
            <a href="#today"><Button size="lg" variant="secondary">See what’s here today</Button></a>
          </motion.div>
        </section>

        <section id="today" className="mx-auto max-w-6xl px-5 pb-20">
          <h2 className="text-2xl font-semibold tracking-tight">What’s here today — and what isn’t</h2>
          <p className="mt-2 max-w-xl text-muted">Madhuora is early. We’d rather be plain about what works now than promise what doesn’t exist yet.</p>
          <ul className="mt-8 grid gap-4 md:grid-cols-3">
            {FEATURES.map((f) => (
              <li key={f.title} className="rounded-[16px] border border-border bg-surface p-5">
                <Chip tone={f.status === "Available" ? "ok" : "soon"}>{f.status}</Chip>
                <h3 className="mt-3 font-semibold">{f.title}</h3>
                <p className="mt-1.5 text-sm text-muted">{f.body}</p>
              </li>
            ))}
          </ul>
        </section>

        <section className="mx-auto max-w-6xl px-5 pb-24">
          <div className="grid gap-8 rounded-[24px] border border-border bg-surface p-8 md:grid-cols-3 md:p-10">
            <div><h3 className="font-semibold">Honest by design</h3><p className="mt-2 text-sm text-muted">A twin is labelled as an AI everywhere. It doesn’t claim to be a person, to have lived experiences it has no record of, or to bring anyone back.</p></div>
            <div><h3 className="font-semibold">Consent first</h3><p className="mt-2 text-sm text-muted">You agree before any external AI processing. Twins of other people will need their consent and human review before they’re possible.</p></div>
            <div><h3 className="font-semibold">Private by default</h3><p className="mt-2 text-sm text-muted">Portraits live in private storage. Your data is hosted in Mumbai and encrypted in transit; replies are generated by an external AI provider.</p></div>
          </div>
        </section>
      </main>

      <footer className="border-t border-border px-5 py-8 text-center text-sm text-muted">
        Named for Madhu Sharma, the founder’s grandmother. · Madhuora is an AI service; it is not a person.
      </footer>
    </div>
  );
}
