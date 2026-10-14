import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { useTheme } from "../hooks/useTheme";
import { Icon, type IconName } from "./Icon";
import { Logo } from "./Logo";

const NAV: { to: string; label: string; icon: IconName; end?: boolean; soon?: boolean }[] = [
  { to: "/app", label: "Home", icon: "home", end: true },
  { to: "/app/studio", label: "Twin Studio", icon: "studio" },
  { to: "/app/conversations", label: "Conversations", icon: "chat", soon: true },
  { to: "/app/memories", label: "Memories", icon: "memory", soon: true },
  { to: "/app/voice", label: "Voice", icon: "voice", soon: true },
  { to: "/app/automations", label: "Automations", icon: "clock", soon: true },
  { to: "/app/settings", label: "Settings", icon: "settings" },
];

function ThemeButton({ compact }: { compact?: boolean }) {
  const { resolved, set } = useTheme();
  const next = resolved === "dark" ? "light" : "dark";
  return (
    <button onClick={() => set(next)} aria-label={`Switch to ${next} theme`}
      className="flex h-10 items-center gap-3 rounded-[10px] px-3 text-sm text-muted hover:bg-surface-2 hover:text-fg">
      <Icon name={resolved === "dark" ? "sun" : "moon"} />
      {!compact && <span>{resolved === "dark" ? "Light theme" : "Dark theme"}</span>}
    </button>
  );
}

function NavList({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  return (
    <nav aria-label="Main" className="flex flex-col gap-1">
      {NAV.map((n) => (
        <NavLink key={n.to} to={n.to} end={n.end} onClick={onNavigate} title={collapsed ? n.label : undefined}
          className={({ isActive }) => `flex h-10 items-center gap-3 rounded-[10px] px-3 text-sm transition duration-150 ${isActive ? "bg-surface-2 font-medium text-fg" : "text-muted hover:bg-surface-2 hover:text-fg"}`}>
          <Icon name={n.icon} />
          {!collapsed && (<><span className="flex-1">{n.label}</span>{n.soon && <span className="rounded-full border border-border px-2 text-[11px] text-muted">Soon</span>}</>)}
          {collapsed && <span className="sr-only">{n.label}</span>}
        </NavLink>
      ))}
    </nav>
  );
}

export function AppShell() {
  const { signOut } = useAuth();
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem("madhuora-sidebar") === "collapsed"; } catch { return false; }
  });
  const [drawer, setDrawer] = useState(false);
  const loc = useLocation();
  const [offline, setOffline] = useState(!navigator.onLine);

  useEffect(() => { document.documentElement.style.setProperty("--sidebar", collapsed ? "72px" : "248px"); try { localStorage.setItem("madhuora-sidebar", collapsed ? "collapsed" : "open"); } catch { /* ignore */ } }, [collapsed]);
  useEffect(() => { setDrawer(false); }, [loc.pathname]);
  useEffect(() => {
    const on = () => setOffline(false), off = () => setOffline(true);
    addEventListener("online", on); addEventListener("offline", off);
    return () => { removeEventListener("online", on); removeEventListener("offline", off); };
  }, []);
  useEffect(() => {
    if (!drawer) return;
    const k = (e: KeyboardEvent) => e.key === "Escape" && setDrawer(false);
    addEventListener("keydown", k);
    return () => removeEventListener("keydown", k);
  }, [drawer]);

  const side = (compact: boolean, mobile = false) => (
    <div className="flex h-full flex-col gap-6 p-3">
      <div className={`flex items-center ${compact ? "justify-center" : "justify-between"} pt-1`}>
        <Logo variant="gold-on-maroon" height={compact ? 14 : 22} padded={!compact ? true : false} className={compact ? "px-1.5 py-2" : ""} />
        {mobile && <button aria-label="Close menu" onClick={() => setDrawer(false)} className="grid size-10 place-items-center rounded-[10px] hover:bg-surface-2"><Icon name="x" /></button>}
      </div>
      <NavList collapsed={compact} onNavigate={() => setDrawer(false)} />
      <div className="mt-auto flex flex-col gap-1">
        <ThemeButton compact={compact} />
        <button onClick={signOut} className="flex h-10 items-center gap-3 rounded-[10px] px-3 text-sm text-muted hover:bg-surface-2 hover:text-fg">
          <Icon name="logout" />{!compact && <span>Sign out</span>}<span className="sr-only">{compact ? "Sign out" : ""}</span>
        </button>
        {!mobile && (
          <button onClick={() => setCollapsed((c) => !c)} aria-label={compact ? "Expand sidebar" : "Collapse sidebar"} aria-expanded={!compact}
            className="flex h-10 items-center gap-3 rounded-[10px] px-3 text-sm text-muted hover:bg-surface-2 hover:text-fg">
            <Icon name="collapse" className={compact ? "rotate-180" : ""} />{!compact && <span>Collapse</span>}
          </button>
        )}
      </div>
    </div>
  );

  return (
    <div className="min-h-screen md:flex">
      <div className="atelier-bg" aria-hidden />
      <aside className="sticky top-0 hidden h-screen shrink-0 border-r border-border bg-surface/80 backdrop-blur md:block"
        style={{ width: collapsed ? 72 : 248, transition: "width 200ms ease" }}>
        {side(collapsed)}
      </aside>

      <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-border bg-surface/90 px-4 backdrop-blur md:hidden">
        <Logo variant="gold-on-maroon" height={18} />
        <button aria-label="Open menu" onClick={() => setDrawer(true)} className="grid size-10 place-items-center rounded-[10px] hover:bg-surface-2"><Icon name="menu" /></button>
      </header>
      {drawer && (
        <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true" aria-label="Menu">
          <button className="absolute inset-0 bg-black/50" aria-label="Close menu" onClick={() => setDrawer(false)} />
          <div className="absolute inset-y-0 left-0 w-72 border-r border-border bg-surface">{side(false, true)}</div>
        </div>
      )}

      <main className="min-w-0 flex-1">
        {offline && <div role="status" className="bg-danger px-4 py-2 text-center text-sm text-on-danger">You are offline. Changes can’t be saved until you reconnect.</div>}
        <div className="mx-auto w-full max-w-5xl px-4 py-8 md:px-8 md:py-12"><Outlet /></div>
      </main>
    </div>
  );
}
