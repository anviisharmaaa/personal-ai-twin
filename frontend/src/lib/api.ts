import { config } from "./config";
import { supabase } from "./supabase";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
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
    const detail = typeof json.detail === "string" ? json.detail : "Something went wrong.";
    throw new ApiError(res.status, detail);
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
  personality: { answers?: Record<string, string | string[]>; submitted_at?: string };
  communication: { formality?: string; length?: string; emoji?: string };
  appearance: { framing?: string; background?: string; lighting?: string; portrait_subject?: string };
  portrait_path: string | null;
  portrait_url: string | null;
  portrait_permission_confirmed: boolean;
};

export type Me = {
  user_id: string;
  profile: { display_name: string | null; timezone: string } | null;
  twin: Twin | null;
  completed_steps: string[];
  ai_consent: { granted: boolean; version: string | null; current_version: string };
};

export type Question = { id: string; prompt: string; multi: boolean; max?: number; options: string[] };
