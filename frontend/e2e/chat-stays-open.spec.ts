import { expect, test, type Page } from "@playwright/test";
import { mockApp, withCharacter } from "./mock";
import { mockChat, newChat, type ChatBackend } from "./mock-chat";

// MOCKED API with realistic latency (see mock-chat.ts: listDelayMs / streamDelayMs). Regression tests for the bug where
// sending a message dropped the user back to "Talk to a character". They prove UI state handling only; they do not prove
// real streaming from Ollama, which is checked by the live procedure.
const MEERA = newChat().chars[0];
const ARJUN = { id: "ch2", name: "Arjun", portrait_url: null, summary: "A gruff retired sailor who speaks in short sentences.", has_description: true, profile_state: "missing" };
const user = (id: string, text: string, key: string) => ({ id, role: "user" as const, content: text, status: "complete", reply_to: null, provider: null, model: null,
  first_token_ms: null, duration_ms: null, failure_code: null, used_memory_ids: [], created_at: "x", client_message_id: key });
const asst = (id: string, text: string, to: string) => ({ ...user(id, text, ""), role: "assistant" as const, reply_to: to, client_message_id: null, provider: "ollama", model: "qwen-test:9b" });

const open = async (page: Page, ch: ChatBackend, url = "/app/conversations?ch=ch1") => {
  await mockApp(page, withCharacter(true), { theme: "dark" });
  await mockChat(page, ch);
  await page.goto(url);
  return ch;
};
const picker = (page: Page) => page.getByRole("heading", { name: "Talk to a character" });
const stillChatting = async (page: Page, who: string) => {
  await expect(page.getByTestId("active-character")).toHaveText(who);
  await expect(picker(page)).toHaveCount(0);
};
const send = async (page: Page, text: string) => {
  await page.getByLabel("Message").fill(text);
  await page.getByRole("button", { name: "Send" }).click();
};
/** Samples the page for `ms` and fails if the picker ever appears: a flash of the picker is the bug, not just its end state. */
const neverPicker = async (page: Page, ms = 1500) => {
  for (let t = 0; t < ms; t += 100) {
    expect(await picker(page).count(), `picker appeared after ${t} ms`).toBe(0);
    await page.waitForTimeout(100);
  }
};
const SOON = { timeout: 600 };       // the UI must not leave the chat even for an instant while the server is slow

test.describe("sending a message keeps you in the conversation", () => {
  test("the first message of a new conversation never shows the character picker, even with a slow conversation list", async ({ page }) => {
    const ch = await open(page, newChat());
    await stillChatting(page, "Meera");
    ch.listDelayMs = 1500;                                   // the list refetch after creating the conversation is slow
    ch.streamDelayMs = 600;
    await send(page, "Hi Meera");
    await neverPicker(page, 1200);
    await expect(page.getByTestId("active-character")).toHaveText("Meera", SOON);
    await expect(page.getByLabel("Message")).toBeVisible(SOON);
    await expect(page.getByText("Hello there, friend.")).toBeVisible();
    await stillChatting(page, "Meera");
    await expect(page).toHaveURL(/c=c\d+/);
    await expect(page).toHaveURL(/ch=ch1/);                  // the character stays in the address as well
    await expect(page.getByRole("list", { name: "Chat history" }).getByText("Hi Meera")).toHaveCount(1);
  });

  test("three consecutive messages stay in the same conversation with the same character", async ({ page }) => {
    const ch = await open(page, newChat());
    ch.listDelayMs = 700;
    for (const [i, text] of ["one", "two", "three"].entries()) {
      await send(page, text);
      await expect(page.getByTestId("active-character")).toHaveText("Meera", SOON);
      await expect(page.getByRole("button", { name: "Send" })).toBeDisabled({ timeout: 4000 });   // composer empty again, reply done
      await expect(page.getByRole("list", { name: "Chat history" }).getByText(text, { exact: true })).toHaveCount(1);
      await stillChatting(page, "Meera");
      expect(ch.calls.filter((c) => c.method === "POST" && c.path.endsWith("/messages/stream"))).toHaveLength(i + 1);
    }
    expect(ch.calls.filter((c) => c.method === "POST" && c.path === "/api/v1/conversations")).toHaveLength(1);   // one conversation
    const cids = new Set(ch.calls.filter((c) => c.path.endsWith("/messages/stream")).map((c) => c.path));
    expect(cids.size).toBe(1);
  });

  test("a conversation-list refetch in the middle of a reply does not drop the chat", async ({ page }) => {
    const ch = await open(page, newChat());
    ch.streamDelayMs = 1200;
    ch.listDelayMs = 900;
    await send(page, "Hello");
    await expect(page.getByTestId("active-character")).toHaveText("Meera", SOON);
    // Focus-style refetch of every stale query while the reply is still being produced.
    await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
    await page.evaluate(() => window.dispatchEvent(new Event("focus")));
    await expect(page.getByTestId("active-character")).toHaveText("Meera", SOON);
    await expect(picker(page)).toHaveCount(0, SOON);
    await expect(page.getByText("Hello there, friend.")).toBeVisible();
    await stillChatting(page, "Meera");
  });

  test("opening a saved conversation by address shows its character, not the picker, while the list loads; reload restores it", async ({ page }) => {
    const ch = newChat({ chars: [MEERA, ARJUN] });
    ch.convs.push({ id: "cA", character_id: "ch2", title: "Sea stories", created_at: "x", last_activity_at: "x", archived_at: null, learning_reviewed_at: null, learning_failure_code: null });
    ch.msgs.cA = [user("mA", "Tell me about the sea", "k1"), asst("mB", "Grey, mostly.", "mA")];
    ch.listDelayMs = 900;
    await open(page, ch, "/app/conversations?c=cA");
    await neverPicker(page, 1200);                             // loading is not "no character chosen"
    await stillChatting(page, "Arjun");
    await expect(page.getByText("Grey, mostly.")).toBeVisible();
    await send(page, "And the wind?");
    await expect(page.getByTestId("active-character")).toHaveText("Arjun", SOON);
    await expect(page.getByText("Hello there, friend.")).toBeVisible();
    await page.reload();
    await expect(picker(page)).toHaveCount(0, SOON);
    await stillChatting(page, "Arjun");
    await expect(page.getByText("Grey, mostly.")).toBeVisible();
    await expect(page.getByRole("list", { name: "Chat history" }).getByText("And the wind?")).toBeVisible();
    await expect(page.getByLabel("Message")).toHaveAttribute("placeholder", "Write a message to Arjun…");
  });

  test("clicking an existing conversation in the sidebar keeps the character", async ({ page }) => {
    const ch = newChat({ chars: [MEERA, ARJUN] });
    ch.convs.push({ id: "cA", character_id: "ch2", title: "Sea stories", created_at: "x", last_activity_at: "x", archived_at: null, learning_reviewed_at: null, learning_failure_code: null });
    ch.msgs.cA = [user("mA", "Tell me about the sea", "k1")];
    await open(page, ch, "/app/conversations?ch=ch2");
    await page.getByRole("button", { name: "Sea stories" }).click();
    await stillChatting(page, "Arjun");
    await expect(page).toHaveURL(/ch=ch2/);
    await send(page, "Again");
    await stillChatting(page, "Arjun");
    await expect(page.getByText("Hello there, friend.")).toBeVisible();
  });

  test("switching character explicitly drops the draft and the stream, and the next message goes to the new character", async ({ page }) => {
    const ch = newChat({ chars: [MEERA, ARJUN] });
    ch.mode = "hang";
    await open(page, ch);
    await send(page, "for Meera only");
    await expect(page.getByRole("button", { name: "Stop" })).toBeVisible();
    await page.getByRole("button", { name: "Change character" }).click();
    await expect(picker(page)).toBeVisible();                  // an explicit choice DOES return to the picker
    await page.getByRole("button", { name: "Talk to Arjun" }).click();
    await stillChatting(page, "Arjun");
    await expect(page.getByLabel("Message")).toHaveValue("");
    ch.mode = "ok";
    await send(page, "for Arjun");
    await stillChatting(page, "Arjun");
    await expect(page.getByText("Hello there, friend.")).toBeVisible();
    const creates = ch.calls.filter((c) => c.method === "POST" && c.path === "/api/v1/conversations").map((c) => (c.body as { character_id: string }).character_id);
    expect(creates).toEqual(["ch1", "ch2"]);
  });

  test("a stream error is shown inside the current conversation, which stays open and keeps the partial text", async ({ page }) => {
    const ch = await open(page, newChat({ mode: "fail" }));
    ch.listDelayMs = 800;
    await send(page, "Hi");
    await expect(page.getByTestId("active-character")).toHaveText("Meera", SOON);
    await expect(page.getByRole("alert").filter({ hasText: "The connection was interrupted" })).toBeVisible();
    await expect(page.getByText("Half of an ans")).toBeVisible();
    await stillChatting(page, "Meera");
    await expect(page.getByRole("button", { name: "Try again" }).first()).toBeVisible();
  });

  test("a refused request is explained in the conversation; the character stays selected", async ({ page }) => {
    const ch = await open(page, newChat({ mode: "refuse", refuseCode: "local_unavailable" }));
    ch.listDelayMs = 500;
    await send(page, "Hi");
    await expect(page.getByTestId("active-character")).toHaveText("Meera", SOON);
    await expect(page.getByRole("alert")).toContainText("Ollama isn’t running");
    await stillChatting(page, "Meera");
    await expect(page.getByLabel("Message")).toBeVisible();
  });

  test("a failed character list refetch keeps the open conversation (an error is not an empty choice)", async ({ page }) => {
    const ch = await open(page, newChat());
    await send(page, "first");
    await expect(page.getByText("Hello there, friend.")).toBeVisible();
    ch.chars = [];                                             // the next character-list fetch is empty/unavailable
    await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
    await page.waitForTimeout(500);
    await expect(page.getByLabel("Message")).toBeVisible();    // the conversation itself is untouched
  });

  test("if the conversation cannot be created, the error appears in the chat, the draft is kept and the character stays", async ({ page }) => {
    const ch = await open(page, newChat({ createRefuses: "not_configured" }));
    await send(page, "Hello?");
    await expect(page.getByRole("alert").filter({ hasText: "Chat isn’t set up on the server yet" })).toBeVisible();
    await stillChatting(page, "Meera");
    await expect(page.getByLabel("Message")).toHaveValue("Hello?");          // nothing the user typed is lost
    ch.createRefuses = null;
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByText("Hello there, friend.")).toBeVisible();
    await stillChatting(page, "Meera");
  });
});
