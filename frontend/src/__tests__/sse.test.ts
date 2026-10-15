import { describe, expect, it } from "vitest";
import { SseParser, StreamError } from "../lib/sse";

const frame = (event: string, data: object) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
const enc = new TextEncoder();

describe("SseParser", () => {
  it("parses whole frames", () => {
    const p = new SseParser();
    const out = p.push(frame("started", { a: 1 }) + frame("delta", { text: "hi" }));
    expect(out).toEqual([{ event: "started", data: { a: 1 } }, { event: "delta", data: { text: "hi" } }]);
    expect(p.hasPartial).toBe(false);
  });

  it("handles a frame split at every possible byte boundary, including inside a multi-byte character", () => {
    const text = frame("delta", { text: "नमस्ते 😀 é" }) + frame("done", { status: "complete" });
    const bytes = enc.encode(text);
    for (let cut = 1; cut < bytes.length; cut++) {
      const p = new SseParser();
      const got = [...p.push(bytes.slice(0, cut)), ...p.push(bytes.slice(cut))];
      expect(got.map((e) => e.event)).toEqual(["delta", "done"]);
      expect(got[0].data.text).toBe("नमस्ते 😀 é");
    }
  });

  it("handles one byte at a time", () => {
    const p = new SseParser();
    const got = [...enc.encode(frame("delta", { text: "ab\ncd" }))].flatMap((b) => p.push(new Uint8Array([b])));
    expect(got).toEqual([{ event: "delta", data: { text: "ab\ncd" } }]);
  });

  it("accepts CRLF, comments and keep-alives", () => {
    const p = new SseParser();
    const out = p.push(`: keep-alive\n\nevent: delta\r\ndata: {"text":"x"}\r\n\r\n`);
    expect(out).toEqual([{ event: "delta", data: { text: "x" } }]);
  });

  it("reports buffered bytes that never became a frame", () => {
    const p = new SseParser();
    expect(p.push('event: delta\ndata: {"te')).toEqual([]);
    expect(p.hasPartial).toBe(true);
  });

  it("rejects a garbled payload instead of guessing", () => {
    const p = new SseParser();
    expect(() => p.push("event: delta\ndata: {not json}\n\n")).toThrow(StreamError);
    expect(() => new SseParser().push('event: delta\ndata: [1,2]\n\n')).toThrow(StreamError);
  });
});
