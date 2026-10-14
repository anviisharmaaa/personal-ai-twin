/**
 * MOCKED-BACKEND e2e helpers. These tests exercise the real frontend in a real browser,
 * but the Madhuora API and Supabase are simulated with route interception. They prove UI
 * behaviour — not that the real backend or database works.
 */
import type { Page, Route } from "@playwright/test";

export const API = "http://localhost:8000";
const CORS = { "access-control-allow-origin": "http://127.0.0.1:5173", "access-control-allow-headers": "*", "access-control-allow-methods": "*" };

const b64 = (o: object) => Buffer.from(JSON.stringify(o)).toString("base64url");
const token = `${b64({ alg: "HS256", typ: "JWT" })}.${b64({ sub: "u1", exp: 4102444800 })}.sig`;
export const SESSION = {
  access_token: token, refresh_token: "r", expires_in: 3600, expires_at: 4102444800, token_type: "bearer",
  user: { id: "u1", aud: "authenticated", role: "authenticated", email: "anvi@example.test", app_metadata: {}, user_metadata: {}, created_at: "2026-10-14T00:00:00Z" },
};

export const QUESTIONS = { questions: [
  { id: "tone", prompt: "How should your twin generally sound?", multi: false, options: ["warm", "playful", "calm", "direct", "formal"] },
  { id: "values", prompt: "Which values matter most to you? (up to 3)", multi: true, max: 3, options: ["family", "honesty", "curiosity", "kindness"] },
] };

type Twin = Record<string, unknown> | null;
export type Backend = {
  twin: Twin; steps: string[]; consent: boolean; calls: { method: string; path: string; body?: unknown }[];
  failTwinSave: boolean;
};

export function newBackend(init: Partial<Backend> = {}): Backend {
  return { twin: null, steps: [], consent: false, calls: [], failTwinSave: false, ...init };
}

export const fullTwin = (over: object = {}) => ({
  id: "t1", name: "Anvi", about: "Curious.", personality: { answers: { tone: "warm" }, submitted_at: "x" },
  communication: {}, appearance: {}, portrait_path: null, portrait_url: null, portrait_permission_confirmed: false, ...over,
});

export async function mockApp(page: Page, be: Backend, opts: { auth?: boolean; theme?: "light" | "dark"; supabase?: (r: Route) => Promise<void> | void } = {}) {
  const { auth = true, theme = "dark" } = opts;
  await page.addInitScript(([s, t, a]) => {
    if (a) localStorage.setItem("sb-mock-auth-token", JSON.stringify(s));
    if (!localStorage.getItem("madhuora-theme")) localStorage.setItem("madhuora-theme", t as string);
  }, [SESSION, theme, auth] as const);

  await page.route("https://mock.supabase.co/**", async (r) => {
    if (opts.supabase) return opts.supabase(r);
    await r.fulfill({ json: {}, headers: { "access-control-allow-origin": "*" } });
  });

  await page.route(`${API}/**`, async (r) => {
    const req = r.request();
    const path = new URL(req.url()).pathname;
    if (req.method() === "OPTIONS") return r.fulfill({ status: 204, headers: CORS });
    let body: unknown;
    try { body = req.postDataJSON(); } catch { body = req.postData() ? "<multipart>" : undefined; }
    be.calls.push({ method: req.method(), path, body });
    const json = (j: unknown, status = 200) => r.fulfill({ status, json: j as object, headers: CORS });

    if (path === "/api/v1/me") {
      return json({
        user_id: "u1", profile: { display_name: "Anvi", timezone: "Asia/Calcutta" }, twin: be.twin, completed_steps: be.steps,
        ai_consent: { granted: be.consent, version: be.consent ? "2026-10-v1" : null, current_version: "2026-10-v1" },
      });
    }
    if (path === "/api/v1/onboarding/questionnaire") return json(QUESTIONS);
    if (path === "/api/v1/consents/ai-processing") { be.consent = req.method() !== "DELETE"; return req.method() === "DELETE" ? r.fulfill({ status: 204, headers: CORS }) : json({ ok: true }, 201); }
    if (path.startsWith("/api/v1/onboarding/steps/")) {
      const step = path.split("/")[5];
      if (!be.steps.includes(step)) be.steps.push(step);
      return json({ step, status: "completed" });
    }
    if (path === "/api/v1/twin" && req.method() === "PUT") {
      if (be.failTwinSave) return json({ detail: "Data service error. Please try again." }, 502);
      be.twin = { ...(be.twin ?? fullTwin({ personality: {} })), ...(body as object) };
      return json(be.twin);
    }
    if (path === "/api/v1/twin/personality") {
      be.twin = { ...(be.twin ?? fullTwin()), personality: { answers: (body as { answers: object }).answers, submitted_at: "now" } };
      return json(be.twin);
    }
    if (path === "/api/v1/twin/portrait" && req.method() === "POST") {
      be.twin = { ...(be.twin ?? fullTwin()), portrait_path: "u1/p.jpg", portrait_url: "data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==" };
      return json(be.twin);
    }
    if (path === "/api/v1/twin/portrait" && req.method() === "DELETE") { be.twin = { ...(be.twin ?? {}), portrait_path: null, portrait_url: null }; return r.fulfill({ status: 204, headers: CORS }); }
    return json({});
  });
}
