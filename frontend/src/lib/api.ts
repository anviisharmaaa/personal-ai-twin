import { config } from "./config";
import { supabase } from "./supabase";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code?: string,
  ) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown, form?: FormData): Promise<T> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 20000);
  let res: Response;
  try {
    res = await fetch(`${config.apiUrl}${path}`, {
      method,
      headers,
      body: form ?? (body !== undefined ? JSON.stringify(body) : undefined),
      signal: ctrl.signal,
    });
  } catch {
    throw new ApiError(0, navigator.onLine ? "The service took too long to respond." : "You appear to be offline.");
  } finally {
    clearTimeout(timer);
  }
  if (res.status === 204) return undefined as T;
  const json = (await res.json().catch(() => ({}))) as { detail?: unknown };
  if (!res.ok) {
    // The API sends either a plain message or {code, message} (character analysis uses codes).
    const d = json.detail;
    if (d && typeof d === "object" && "message" in d) {
      const o = d as { code?: string; message: string };
      throw new ApiError(res.status, o.message, o.code);
    }
    throw new ApiError(res.status, typeof d === "string" ? d : "Something went wrong.");
  }
  return json as T;
}

export const api = {
  get: <T>(p: string) => request<T>("GET", p),
  put: <T>(p: string, b: unknown) => request<T>("PUT", p, b),
  post: <T>(p: string, b?: unknown) => request<T>("POST", p, b),
  del: (p: string) => request<void>("DELETE", p),
  upload: <T>(p: string, f: FormData) => request<T>("POST", p, undefined, f),
};

// ---- Types mirrored from the backend ----
export type Twin = {
  id: string;
  name: string;
  about: string | null;
  /** The user's own words. The source of truth; the profile below is only an interpretation of it. */
  character_description: string;
  character_version: number;
  appearance: { framing?: string; background?: string; lighting?: string; portrait_subject?: string };
  portrait_path: string | null;
  portrait_url: string | null;
  portrait_permission_confirmed: boolean;
};

export type Basis = "stated" | "inferred" | "context_dependent";
export type Item = { text: string; basis: Basis };
export type CharacterProfile = {
  summary: string;
  core_traits: Item[];
  speaking_style: Item[];
  typical_expressions: string[];
  warmth_and_expressiveness: Item[];
  humour_and_playfulness: Item[];
  empathy_and_support: Item[];
  directness_and_disagreement: Item[];
  values_and_motivations: Item[];
  relationships_and_social: Item[];
  interests_and_habits: Item[];
  communication_preferences: Item[];
  boundaries_and_careful_topics: Item[];
  context_tendencies: { context: string; tendency: string; basis: Basis }[];
  response_patterns: Item[];
  behavioural_guidance: string[];
  uncertainties: string[];
};

export type CharacterState = {
  status: "empty" | "not_analysed" | "current" | "outdated";
  description_version: number;
  min_chars: number;
  profile: CharacterProfile | null;
  profile_version: number | null;
  generated_at: string | null;
  /** Code of the most recent failed attempt, if it happened after the last good profile. */
  failure: string | null;
};

export type Me = {
  user_id: string;
  profile: { display_name: string | null; timezone: string } | null;
  twin: Twin | null;
  character: CharacterState | null;
  completed_steps: string[];
  ai_consent: { granted: boolean; version: string | null; current_version: string };
};
