/**
 * MOCKED chat/learning API for Playwright. The real frontend runs in a real browser; the server is simulated.
 * IMPORTANT: Playwright can only fulfil a request in one piece, so the "stream" here arrives as a single body. The
 * parser's handling of split chunks and split UTF-8 is unit-tested in src/__tests__/sse.test.ts, and real incremental
 * streaming from Ollama is only checked by the live procedure in docs/LIVE_VERIFICATION.md.
 */
import type { Page } from "@playwright/test";
import { API } from "./mock";

const CORS = { "access-control-allow-origin": "http://127.0.0.1:5173", "access-control-allow-headers": "*", "access-control-allow-methods": "*" };

type Msg = { id: string; role: "user" | "assistant"; content: string; status: string; reply_to: string | null; provider: string | null; model: string | null;
  first_token_ms: number | null; duration_ms: number | null; failure_code: string | null; used_memory_ids: string[]; created_at: string; client_message_id: string | null };
type Conv = { id: string; title: string; created_at: string; last_activity_at: string; archived_at: null; learning_reviewed_at: string | null; learning_failure_code: string | null };
type Cand = { id: string; statement: string; category: string; scope: string; evidence_type: string; supporting: { message_id: string; quote: string }[]; status: string; conversation_id: string | null; created_at: string };
type Mem = Cand & { source_deleted: boolean; edited: boolean; pinned: boolean; superseded_by: null; updated_at: string };
type Prop = { id: string; memory_id: string; section: string; current_text: string; proposed_text: string; kind: string; evidence: string[]; status: string; created_at: string; resolved_at: null };

export type ChatBackend = {
  reason: string | null; isSample: boolean; modelBusy: boolean; profileOutdated: boolean; profileState: string;
  /** ok: stream a reply. fail: stream a failure after some text. hang: never answer (for Stop). refuse: HTTP error. */
  mode: "ok" | "fail" | "hang" | "refuse"; reply: string; refuseCode: string;
  convs: Conv[]; msgs: Record<string, Msg[]>; learning: boolean;
  candidates: Cand[]; memories: Mem[]; proposals: Prop[]; revisions: { id: string; profile: object; reason: string; proposal_id: string | null; created_at: string }[];
  reviewing: boolean; reviewResult: Cand[]; conflictOnApprove: boolean;
  calls: { method: string; path: string; body?: unknown }[]; n: number;
};

export const newChat = (init: Partial<ChatBackend> = {}): ChatBackend => ({
  reason: null, isSample: false, modelBusy: false, profileOutdated: false, profileState: "current", mode: "ok", reply: "Hello there, friend.", refuseCode: "model_busy",
  convs: [], msgs: {}, learning: false, candidates: [], memories: [], proposals: [], revisions: [], reviewing: false, reviewResult: [],
  conflictOnApprove: false, calls: [], n: 0, ...init,
});

const sse = (event: string, data: object) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
const now = () => "2026-10-15T09:00:00+00:00";

export const sampleCandidate = (over: Partial<Cand> = {}): Cand => ({
  id: "cand1", statement: "She likes masala chai in the mornings", category: "preference", scope: "", evidence_type: "explicit_statement",
  supporting: [{ message_id: "m-u1", quote: "I really like masala chai in the mornings" }], status: "pending", conversation_id: "c1", created_at: now(), ...over,
});

export async function mockChat(page: Page, ch: ChatBackend) {
  await page.route(`${API}/**`, async (r) => {
    const req = r.request();
    const path = new URL(req.url()).pathname;
    const m = req.method();
    const watched = /^\/api\/v1\/(chat|conversations|learning|memory|memories|profile-)/.test(path);
    if (!watched || m === "OPTIONS") return r.fallback();
    let body: Record<string, unknown> = {};
    try { body = req.postDataJSON() ?? {}; } catch { /* no body */ }
    ch.calls.push({ method: m, path, body });
    const json = (j: unknown, status = 200) => r.fulfill({ status, json: j as object, headers: CORS });
    const err = (status: number, code: string, message: string, extra: object = {}) => json({ detail: { code, message, ...extra } }, status);
    const none = () => r.fulfill({ status: 204, headers: CORS });

    if (path === "/api/v1/chat/status") {
      return json({ available: ch.reason === null, reason: ch.reason, provider: ch.isSample ? "mock" : "ollama", is_sample: ch.isSample, model_busy: ch.modelBusy,
        profile_state: ch.profileState, profile_outdated: ch.profileOutdated, limits: { max_user_chars: 4000, context_messages: 24 } });
    }
    if (path === "/api/v1/conversations" && m === "GET") return json({ conversations: ch.convs });
    if (path === "/api/v1/conversations" && m === "POST") {
      const c: Conv = { id: `c${++ch.n}`, title: "New conversation", created_at: now(), last_activity_at: now(), archived_at: null, learning_reviewed_at: null, learning_failure_code: null };
      ch.convs.unshift(c); ch.msgs[c.id] = [];
      return json(c, 201);
    }
    let mm = path.match(/^\/api\/v1\/conversations\/([^/]+)\/messages$/);
    if (mm && m === "GET") return json({ messages: ch.msgs[mm[1]] ?? [], generating: false });
    mm = path.match(/^\/api\/v1\/conversations\/([^/]+)\/messages\/stream$/);
    if (mm && m === "POST") {
      const cid = mm[1];
      const text = String(body.content), key = String(body.client_message_id);
      if (ch.mode === "refuse") return err(ch.refuseCode === "model_busy" ? 429 : 503, ch.refuseCode, "refused by the mock");
      let user = ch.msgs[cid].find((x) => x.client_message_id === key);
      if (!user) {
        user = { id: `u${++ch.n}`, role: "user", content: text, status: "complete", reply_to: null, provider: null, model: null, first_token_ms: null, duration_ms: null,
          failure_code: null, used_memory_ids: [], created_at: now(), client_message_id: key };
        ch.msgs[cid].push(user);
        const c = ch.convs.find((x) => x.id === cid); if (c && c.title === "New conversation") c.title = text.slice(0, 40);
      }
      ch.msgs[cid] = ch.msgs[cid].filter((x) => !(x.role === "assistant" && x.reply_to === user!.id && x.status !== "complete"));
      if (ch.mode === "hang") return; // never answers: the browser's Stop is what ends this
      const used = ch.memories.filter((x) => x.status === "active");
      const aid = `a${++ch.n}`;
      const started = sse("started", { user_message_id: user.id, assistant_message_id: aid, provider: "ollama", model: "qwen-test:9b", is_sample: ch.isSample, replayed: false,
        context: { earlier_messages_used: 0, total: 0, trimmed: false }, profile_outdated: false, memories_used: used.map((x) => ({ id: x.id, statement: x.statement })) });
      const asst: Msg = { id: aid, role: "assistant", content: "", status: "complete", reply_to: user.id, provider: "ollama", model: "qwen-test:9b", first_token_ms: 1200, duration_ms: 3400,
        failure_code: null, used_memory_ids: used.map((x) => x.id), created_at: now(), client_message_id: null };
      if (ch.mode === "fail") {
        asst.content = "Half of an ans"; asst.status = "failed"; asst.failure_code = "interrupted"; ch.msgs[cid].push(asst);
        return r.fulfill({ status: 200, headers: { ...CORS, "content-type": "text/event-stream" },
          body: started + sse("delta", { text: asst.content }) + sse("error", { code: "interrupted", assistant_message_id: aid, message: "The connection was interrupted.", partial_saved: true }) });
      }
      asst.content = ch.reply; ch.msgs[cid].push(asst);
      const parts = ch.reply.match(/.{1,6}/g) ?? [];
      return r.fulfill({ status: 200, headers: { ...CORS, "content-type": "text/event-stream" },
        body: started + parts.map((p) => sse("delta", { text: p })).join("") + sse("done", { assistant_message_id: aid, status: "complete", first_token_ms: 1200, duration_ms: 3400, correction_hint: /^no,/i.test(text) }) });
    }
    mm = path.match(/^\/api\/v1\/conversations\/([^/]+)$/);
    if (mm && m === "DELETE") {
      const keep = new URL(req.url()).searchParams.get("delete_memories") === "true";
      ch.convs = ch.convs.filter((c) => c.id !== mm![1]);
      if (keep) ch.memories = ch.memories.filter((x) => x.conversation_id !== mm![1]);
      else ch.memories.forEach((x) => { if (x.conversation_id === mm![1]) { x.source_deleted = true; x.supporting = []; } });
      return none();
    }
    if (path === "/api/v1/learning/preference") {
      if (m === "PUT") ch.learning = body.enabled === true;
      return json({ enabled: ch.learning, enabled_at: null, disabled_at: null, accepted_disclosure_version: ch.learning ? "v1" : null, current_disclosure_version: "v1" });
    }
    mm = path.match(/^\/api\/v1\/conversations\/([^/]+)\/learning\/review$/);
    if (mm && m === "POST") {
      if (!ch.learning) return err(403, "learning_disabled", "Learning from conversations is switched off.");
      ch.reviewing = true;
      setTimeout(() => { ch.reviewing = false; ch.candidates.push(...ch.reviewResult); const c = ch.convs.find((x) => x.id === mm![1]); if (c) c.learning_reviewed_at = now(); }, 300);
      return json({ state: "running", conversation_id: mm[1] }, 202);
    }
    mm = path.match(/^\/api\/v1\/conversations\/([^/]+)\/learning$/);
    if (mm) {
      const c = ch.convs.find((x) => x.id === mm![1]);
      return json({ state: ch.reviewing ? "running" : "idle", reviewed_at: c?.learning_reviewed_at ?? null, failure_code: null, candidates: ch.candidates.filter((x) => x.conversation_id === mm![1]) });
    }
    if (path === "/api/v1/memory/candidates") return json({ candidates: ch.candidates });
    mm = path.match(/^\/api\/v1\/memory\/candidates\/([^/]+)\/(approve|reject)$/);
    if (mm) {
      const c = ch.candidates.find((x) => x.id === mm![1])!;
      if (mm[2] === "reject") { ch.candidates = ch.candidates.filter((x) => x !== c); return json({ id: c.id, status: "rejected" }); }
      if (ch.conflictOnApprove && !body.resolution) return err(409, "conflict", "This overlaps.", { conflicting: [{ id: "old", statement: "She drinks tea every evening" }] });
      ch.candidates = ch.candidates.filter((x) => x !== c);
      const mem: Mem = { ...c, statement: String(body.statement ?? c.statement), status: "active", source_deleted: false, edited: !!body.statement, pinned: false, superseded_by: null, updated_at: now() };
      if (body.resolution === "replace") ch.memories = ch.memories.filter((x) => x.id !== "old");
      ch.memories.push(mem);
      return json({ memory: mem, profile_proposal: null }, 201);
    }
    if (path === "/api/v1/memories" && m === "GET") return json({ memories: ch.memories });
    mm = path.match(/^\/api\/v1\/memories\/([^/]+)$/);
    if (mm && m === "DELETE") { ch.memories = ch.memories.filter((x) => x.id !== mm![1]); return none(); }
    if (mm && m === "PATCH") { const x = ch.memories.find((y) => y.id === mm![1])!; Object.assign(x, body, body.statement ? { edited: true } : {}); return json({ memory: x }); }
    mm = path.match(/^\/api\/v1\/memories\/([^/]+)\/profile-proposal$/);
    if (mm) {
      const p: Prop = { id: `p${++ch.n}`, memory_id: mm[1], section: String(body.section), current_text: "", proposed_text: ch.memories.find((x) => x.id === mm![1])?.statement ?? "", kind: "new_evidence", evidence: [], status: "pending", created_at: now(), resolved_at: null };
      ch.proposals.push(p);
      return json({ profile_proposal: p }, 201);
    }
    if (path === "/api/v1/profile-proposals") return json({ proposals: ch.proposals });
    mm = path.match(/^\/api\/v1\/profile-proposals\/([^/]+)\/resolve$/);
    if (mm) {
      const p = ch.proposals.find((x) => x.id === mm![1])!;
      if (body.action === "accept") { ch.revisions.push({ id: `r${++ch.n}`, profile: { summary: "Before the change" }, reason: "proposal_accepted", proposal_id: p.id, created_at: now() }); }
      if (body.action !== "defer") ch.proposals = ch.proposals.filter((x) => x !== p); else p.status = "deferred";
      return json({ id: p.id, status: body.action });
    }
    if (path === "/api/v1/profile-revisions") return json({ revisions: ch.revisions });
    return json({});
  });
}
