import { ApiError } from "./api";
import { config } from "./config";
import { supabase } from "./supabase";

/** One server-sent event. `data` is the parsed JSON payload. */
export type SseEvent = { event: string; data: Record<string, unknown> };

export class StreamError extends Error {
  constructor(public code: string, message: string) {
    super(message);
  }
}

/**
 * Incremental parser for the `event:` / `data:` frames the chat endpoint sends. It is fed raw bytes in whatever
 * pieces the network delivers: a frame, a line, or even one UTF-8 character may be split across chunks.
 */
export class SseParser {
  private decoder = new TextDecoder("utf-8");
  private buf = "";

  push(chunk: Uint8Array | string): SseEvent[] {
    this.buf += typeof chunk === "string" ? chunk : this.decoder.decode(chunk, { stream: true });
    this.buf = this.buf.replace(/\r\n/g, "\n");
    const out: SseEvent[] = [];
    let at: number;
    while ((at = this.buf.indexOf("\n\n")) >= 0) {
      const frame = this.buf.slice(0, at);
      this.buf = this.buf.slice(at + 2);
      const ev = this.frame(frame);
      if (ev) out.push(ev);
    }
    return out;
  }

  /** True when bytes are buffered that never formed a complete frame (the stream was cut off mid-frame). */
  get hasPartial(): boolean {
    return this.buf.trim().length > 0;
  }

  private frame(frame: string): SseEvent | null {
    let event = "message";
    const data: string[] = [];
    for (const line of frame.split("\n")) {
      if (!line || line.startsWith(":")) continue; // blank line or comment/keep-alive
      const i = line.indexOf(":");
      const field = i < 0 ? line : line.slice(0, i);
      const value = i < 0 ? "" : line.slice(i + 1).replace(/^ /, "");
      if (field === "event") event = value;
      else if (field === "data") data.push(value);
    }
    if (!data.length) return null;
    try {
      const parsed: unknown = JSON.parse(data.join("\n"));
      if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("not an object");
      return { event, data: parsed as Record<string, unknown> };
    } catch {
      throw new StreamError("invalid_stream", "The reply stream was garbled.");
    }
  }
}

export type MemoryUsed = { id: string; statement: string };
export type StartedInfo = {
  user_message_id: string; assistant_message_id: string; provider: string; model: string; is_sample: boolean;
  replayed: boolean; profile_outdated: boolean; character?: { id: string; name: string }; memories_used: MemoryUsed[];
  context: { earlier_messages_used: number; total: number; trimmed: boolean };
};
export type StreamResult =
  | { kind: "done"; content?: string; firstTokenMs: number | null; durationMs: number | null; correctionHint: boolean }
  | { kind: "error"; code: string; message: string; partial: boolean };

export type StreamHandlers = {
  onStarted?: (s: StartedInfo) => void;
  onDelta?: (text: string) => void;
};

/**
 * Sends a message and reads the streamed reply. Deliberately NOT built on the generic JSON helper, which gives up after
 * 20 s: a local model can take minutes to produce its first word. The only ways this ends early are the server closing
 * the stream or the caller aborting `signal` (the Stop button).
 */
export async function streamMessage(
  conversationId: string, content: string, clientMessageId: string, handlers: StreamHandlers, signal: AbortSignal,
): Promise<StreamResult> {
  const { data } = await supabase.auth.getSession();
  const headers: Record<string, string> = { "Content-Type": "application/json", Accept: "text/event-stream" };
  if (data.session?.access_token) headers.Authorization = `Bearer ${data.session.access_token}`;
  let res: Response;
  try {
    res = await fetch(`${config.apiUrl}/api/v1/conversations/${encodeURIComponent(conversationId)}/messages/stream`, {
      method: "POST", headers, signal, body: JSON.stringify({ content, client_message_id: clientMessageId }),
    });
  } catch (e) {
    if (signal.aborted) throw e;
    throw new ApiError(0, navigator.onLine ? "Couldn’t reach the server." : "You appear to be offline.");
  }
  if (!res.ok) {
    const j = (await res.json().catch(() => ({}))) as { detail?: unknown };
    const d = j.detail;
    if (d && typeof d === "object" && "message" in d) {
      const o = d as { code?: string; message: string };
      throw new ApiError(res.status, o.message, o.code);
    }
    throw new ApiError(res.status, typeof d === "string" ? d : "Something went wrong.");
  }
  if (!res.body) throw new StreamError("invalid_stream", "The server sent no reply stream.");

  const parser = new SseParser();
  const reader = res.body.getReader();
  let result: StreamResult | null = null;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      for (const ev of parser.push(value)) {
        if (ev.event === "started") handlers.onStarted?.(ev.data as unknown as StartedInfo);
        else if (ev.event === "delta" && typeof ev.data.text === "string") handlers.onDelta?.(ev.data.text);
        else if (ev.event === "done") {
          result = {
            kind: "done", content: typeof ev.data.content === "string" ? ev.data.content : undefined,
            firstTokenMs: (ev.data.first_token_ms as number | null) ?? null,
            durationMs: (ev.data.duration_ms as number | null) ?? null, correctionHint: ev.data.correction_hint === true,
          };
        } else if (ev.event === "error") {
          result = { kind: "error", code: String(ev.data.code ?? "interrupted"), message: String(ev.data.message ?? "The reply stopped."), partial: ev.data.partial_saved === true };
        }
      }
      if (result) break;
    }
  } finally {
    // Stop reading and release the connection. On Stop the server notices the disconnect and saves the partial text.
    reader.cancel().catch(() => undefined);
  }
  if (!result) {
    if (signal.aborted) throw new DOMException("Stopped", "AbortError");
    throw new StreamError("interrupted", "The connection was interrupted before the reply finished.");
  }
  return result;
}
