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

/** Test data only. This is a hand-written stand-in for what a model might return; it is never real AI output. */
export const MOCK_PROFILE = {
  summary: "Warm and teasing with close friends, careful with people she has just met.",
  core_traits: [{ text: "Shows care through actions rather than words", basis: "stated" }],
  speaking_style: [{ text: "Plain and direct", basis: "inferred" }],
  typical_expressions: ["Eat something first."],
  warmth_and_expressiveness: [], humour_and_playfulness: [{ text: "Teases her closest friends", basis: "stated" }],
  empathy_and_support: [], directness_and_disagreement: [], values_and_motivations: [], relationships_and_social: [],
  interests_and_habits: [], communication_preferences: [], boundaries_and_careful_topics: [],
  context_tendencies: [{ context: "Around strangers", tendency: "Quiet and observant", basis: "stated", evidence: "goes quiet around people she has just met" }],
  response_patterns: [], behavioural_guidance: ["Listen first, then give an honest view."],
  uncertainties: ["How she behaves at work is not described."],
};

type Twin = Record<string, unknown> | null;
type Character = { description: string; version: number; profile: object | null; profileVersion: number | null; failure: string | null };
export type Backend = {
  twin: Twin; steps: string[]; consent: boolean; calls: { method: string; path: string; body?: unknown }[];
  failTwinSave: boolean;
  character: Character;
  aiConfigured: boolean;
  /** Which provider the mocked server reports. "mock" returns a sample-labelled profile. */
  provider: "nvidia" | "ollama" | "mock" | "none";
  /** "ok" returns the mock profile; any other value is returned as an error code from the analysis endpoint. */
  analyze: string;
  analyzeDelayMs: number;
  /** Set while the mock server is "generating" (the real server answers 202 and works on in the background). */
  runningSince?: string | null;
};

export function newBackend(init: Partial<Backend> = {}): Backend {
  return {
    twin: null, steps: [], consent: false, calls: [], failTwinSave: false, aiConfigured: true, provider: "nvidia", analyze: "ok",
    analyzeDelayMs: 0, character: { description: "", version: 0, profile: null, profileVersion: null, failure: null },
    ...init,
  };
}

export const DESCRIPTION = "Meera teases her closest friends constantly but goes quiet around people she has just met.";

export const fullTwin = (over: object = {}) => ({
  id: "t1", name: "Anvi", about: "Curious.", character_description: "", character_version: 0,
  appearance: {}, portrait_path: null, portrait_url: null, portrait_permission_confirmed: false, ...over,
});

/** A backend whose twin already has a saved description (version 1), optionally already analysed. */
export const withCharacter = (analysed = false, over: Partial<Backend> = {}) =>
  newBackend({
    consent: true, steps: ["welcome", "identity", "personality"], twin: fullTwin({ character_description: DESCRIPTION, character_version: 1 }),
    character: { description: DESCRIPTION, version: 1, profile: analysed ? MOCK_PROFILE : null, profileVersion: analysed ? 1 : null, failure: null },
    ...over,
  });

export const PROVIDERS = {
  nvidia: { id: "nvidia", label: "NVIDIA", external: true, development_only: true,
    disclosure: ["The character description you write is sent from Madhuora's server to NVIDIA's hosted API (NVIDIA NIM at build.nvidia.com), which runs outside India.",
      "While this provider is active, please use fictional or non-sensitive descriptions only."] },
  ollama: { id: "ollama", label: "Ollama (local model)", external: false, local: true, development_only: false,
    disclosure: ["The character description you write is analysed by an AI model running through Ollama on the computer that runs Madhuora's server. This provider does not send it to a cloud AI service.",
      "Madhuora itself is not entirely local: sign-in uses Supabase, and your description and the interpretation are saved in your Madhuora database like the rest of your twin."] },
  mock: { id: "mock", label: "Sample (no AI)", external: false, development_only: true,
    disclosure: ["This server is in sample mode. No AI model is used and nothing you write leaves Madhuora."] },
  none: { id: "none", label: "None", external: false, development_only: false,
    disclosure: ["No AI provider is configured on this server, so no AI analysis can run."] },
};

const view = (be: Backend) => {
  const c = be.character;
  const status = !c.description.trim() ? "empty" : c.profile === null ? "not_analysed" : c.profileVersion === c.version ? "current" : "outdated";
  return { status, description_version: c.version, min_chars: 40, profile: c.profile, profile_version: c.profile ? c.profileVersion : null,
    generated_at: c.profile ? "2026-10-14T09:00:00+00:00" : null,
    generated_by: c.profile ? (be.provider === "mock" ? { provider: "mock", model: "sample-fixture", is_sample: true }
      : be.provider === "ollama" ? { provider: "ollama", model: "qwen-test:9b", is_sample: false }
      : { provider: "nvidia", model: "nvidia/test-model", is_sample: false }) : null,
    failure: c.failure,
    analysis: be.runningSince ? { state: "running", started_at: be.runningSince } : { state: "idle", started_at: null } };
};

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
        user_id: "u1", profile: { display_name: "Anvi", timezone: "Asia/Calcutta" },
        twin: be.twin ? { ...be.twin, character_description: be.character.description, character_version: be.character.version } : null,
        character: be.twin ? view(be) : null, completed_steps: be.steps,
        ai_consent: { granted: be.consent, version: be.consent ? "2026-10-v3-x" : null, current_version: "2026-10-v3-x", provider: PROVIDERS[be.provider] },
      });
    }
    if (path === "/ready") return json({ status: "ok", ai_provider: be.provider, configured: { supabase: true, ai: be.aiConfigured } });
    if (path === "/api/v1/twin/character" && req.method() === "PUT") {
      const b = body as { description: string; base_version: number };
      if (b.description !== be.character.description) {
        if (b.base_version !== be.character.version) return json({ detail: { code: "changed_elsewhere", message: "This description changed in another tab or device. Reload to see the latest before editing." } }, 409);
        be.character = { ...be.character, description: b.description, version: be.character.version + 1 };
      }
      return json({ twin: be.twin, character: view(be) });
    }
    if (path === "/api/v1/twin/character/analyze") {
      // Mirrors the real server: answer 202 at once, then finish (or fail) in the background; /me shows the state.
      const version = (body as { version: number }).version;
      if (be.runningSince) return json({ detail: { code: "in_progress", message: "An analysis is already running." } }, 409);
      be.runningSince = new Date().toISOString();
      setTimeout(() => {
        be.runningSince = null;
        be.character = be.analyze !== "ok"
          ? { ...be.character, failure: be.analyze }
          : { ...be.character, profile: MOCK_PROFILE, profileVersion: version, failure: null };
      }, be.analyzeDelayMs || 50);
      return json({ character: view(be), cached: false }, 202);
    }
    if (path === "/api/v1/consents/ai-processing") { be.consent = req.method() !== "DELETE"; return req.method() === "DELETE" ? r.fulfill({ status: 204, headers: CORS }) : json({ ok: true }, 201); }
    if (path.startsWith("/api/v1/onboarding/steps/")) {
      const step = path.split("/")[5];
      if (!be.steps.includes(step)) be.steps.push(step);
      return json({ step, status: "completed" });
    }
    if (path === "/api/v1/twin" && req.method() === "PUT") {
      if (be.failTwinSave) return json({ detail: "Data service error. Please try again." }, 502);
      be.twin = { ...(be.twin ?? fullTwin()), ...(body as object) };
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
