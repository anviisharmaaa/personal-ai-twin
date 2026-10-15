/**
 * MOCKED multi-character API for Playwright, layered over mockApp (the self-twin, id "t1", still comes from /me).
 * Proves UI behaviour only; it is not evidence about the real backend, database or RLS.
 */
import type { Page } from "@playwright/test";
import { API } from "./mock";

const CORS = { "access-control-allow-origin": "http://127.0.0.1:5173", "access-control-allow-headers": "*", "access-control-allow-methods": "*" };

export type Ch = { id: string; name: string; description: string; version: number; portrait_url: string | null };
export type CharBackend = {
  extra: Ch[]; failCreate: string | null; n: number; selfName: string; selfDescription: string;
  calls: { method: string; path: string; search: string; body?: unknown }[];
};
export const newChars = (init: Partial<CharBackend> = {}): CharBackend => ({
  extra: [], failCreate: null, n: 1, selfName: "Anvi", selfDescription: "", calls: [], ...init,
});

const state = (c: { version: number; description: string }) => ({
  status: !c.description.trim() ? "empty" : "not_analysed", description_version: c.version, min_chars: 40, profile: null, profile_version: null,
  generated_at: null, generated_by: null, failure: null, analysis: { state: "idle", started_at: null },
});
const twin = (c: Ch) => ({ id: c.id, name: c.name, about: null, character_description: c.description, character_version: c.version,
  appearance: {}, portrait_path: null, portrait_url: c.portrait_url, portrait_permission_confirmed: false });

export async function mockCharacters(page: Page, cb: CharBackend) {
  await page.route(`${API}/**`, async (r) => {
    const req = r.request();
    const url = new URL(req.url());
    const path = url.pathname;
    const watched = path.startsWith("/api/v1/characters") || (/^\/api\/v1\/twin(\/character)?$/.test(path) && url.searchParams.has("character_id"));
    if (!watched || req.method() === "OPTIONS") return r.fallback();
    let body: Record<string, unknown> = {};
    try { body = req.postDataJSON() ?? {}; } catch { /* none */ }
    cb.calls.push({ method: req.method(), path, search: url.search, body });
    const json = (j: unknown, status = 200) => r.fulfill({ status, json: j as object, headers: CORS });
    const err = (status: number, code: string, message: string) => json({ detail: { code, message } }, status);
    const find = (id: string | null) => cb.extra.find((c) => c.id === id);

    if (path === "/api/v1/characters" && req.method() === "GET") {
      const self = { id: "t1", name: cb.selfName, is_self: true, portrait_url: null, summary: cb.selfDescription, has_description: !!cb.selfDescription, profile_state: "missing", conversation_count: 0, last_activity_at: null };
      return json({ characters: [self, ...cb.extra.map((c) => ({ id: c.id, name: c.name, is_self: false, portrait_url: c.portrait_url, summary: c.description.slice(0, 200), has_description: !!c.description, profile_state: "missing", conversation_count: 0, last_activity_at: null }))] });
    }
    if (path === "/api/v1/characters" && req.method() === "POST") {
      if (cb.failCreate === "migration_required") return err(503, "migration_required", "The database hasn't been upgraded to hold more than one character yet. Apply the latest migration (20261015200000_multiple_characters) and try again.");
      const name = String(body.name ?? "").trim();
      if (!name) return err(422, "invalid_name", "Give the character a name.");
      const c: Ch = { id: `ch${++cb.n}`, name, description: String(body.description ?? ""), version: body.description ? 1 : 0, portrait_url: null };
      cb.extra.push(c);
      return json({ twin: twin(c), character: state(c) }, 201);
    }
    let m = path.match(/^\/api\/v1\/characters\/([^/]+)$/);
    if (m) {
      const c = find(m[1]);
      return c ? json({ twin: twin(c), character: state(c) }) : err(404, "character_not_found", "That character doesn't exist.");
    }
    const target = find(url.searchParams.get("character_id"));
    if (!target) return err(404, "character_not_found", "That character doesn't exist.");
    if (path === "/api/v1/twin" && req.method() === "PUT") { if (body.name) target.name = String(body.name); return json(twin(target)); }
    m = path.match(/^\/api\/v1\/twin\/character$/);
    if (m && req.method() === "PUT") {
      if (String(body.description) !== target.description) {
        if (body.base_version !== target.version) return err(409, "changed_elsewhere", "This description changed in another tab or device. Reload to see the latest before editing.");
        target.description = String(body.description); target.version += 1;
      }
      return json({ twin: twin(target), character: state(target) });
    }
    return json({});
  });
}
