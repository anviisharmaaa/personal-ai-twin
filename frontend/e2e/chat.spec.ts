import { expect, test } from "@playwright/test";
import { mockApp, withCharacter } from "./mock";
import { mockChat, newChat, sampleCandidate } from "./mock-chat";

// MOCKED API (see mock-chat.ts). These prove UI behaviour only, not real streaming, a real model or real RLS.
// By default the character is already chosen (?ch=), as it is after clicking "Talk to Meera"; pass a url to start elsewhere.
const open = async (page: import("@playwright/test").Page, ch = newChat(), theme: "light" | "dark" = "dark", url = "/app/conversations?ch=ch1") => {
  await mockApp(page, withCharacter(true), { theme });
  await mockChat(page, ch);
  await page.goto(url);
  return ch;
};
const ARJUN = { id: "ch2", name: "Arjun", portrait_url: null, summary: "A gruff retired sailor who speaks in short sentences.", has_description: true, profile_state: "missing" };
const streamCalls = (ch: ReturnType<typeof newChat>) => ch.calls.filter((c) => c.method === "POST" && c.path.endsWith("/messages/stream"));


test.describe("character-centred conversations", () => {
  test("picker offers the character; choosing it shows who you are talking to", async ({ page }) => {
    await open(page, newChat(), "dark", "/app/conversations");
    await expect(page.getByRole("heading", { name: "Talk to a character" })).toBeVisible();
    await expect(page.getByText("Warm with friends, quiet at parties")).toBeVisible();
    await expect(page.getByLabel("Message")).toHaveCount(0);                 // no composer until a character is chosen
    await page.getByRole("button", { name: "Talk to Meera" }).click();
    await expect(page.getByTestId("active-character")).toHaveText("Meera");
    await expect(page.getByText("You are talking to")).toBeVisible();
    await expect(page.getByLabel("Message")).toHaveAttribute("placeholder", "Write a message to Meera…");
    await expect(page.getByRole("link", { name: /^[a-z0-9-]{20,}$/ })).toHaveCount(0);   // no internal ids shown
  });

  test("a user with no character is sent to create one", async ({ page }) => {
    await open(page, newChat({ chars: [] }), "dark", "/app/conversations");
    await expect(page.getByText("You haven’t created a character yet.")).toBeVisible();
    await expect(page.getByRole("link", { name: "Create your character" })).toBeVisible();
  });

  test("a made-up or foreign character id is refused, not shown as a chat", async ({ page }) => {
    const ch = await open(page, newChat(), "dark", "/app/conversations?ch=someone-elses-id");
    await expect(page.getByText("That character isn’t available.")).toBeVisible();
    await expect(page.getByLabel("Message")).toHaveCount(0);
    expect(streamCalls(ch)).toHaveLength(0);
    await page.getByRole("button", { name: "Choose a character" }).click();
    await expect(page.getByRole("heading", { name: "Talk to a character" })).toBeVisible();
  });

  test("conversations belong to their character; a second chat with the same character keeps the first", async ({ page }) => {
    const ch = await open(page, newChat({ chars: [newChat().chars[0], ARJUN] }), "dark", "/app/conversations");
    await page.getByRole("button", { name: "Talk to Meera" }).click();
    await page.getByLabel("Message").fill("Hello Meera, first chat");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByText("Hello there, friend.").first()).toBeVisible();
    expect(ch.calls.find((c) => c.method === "POST" && c.path === "/api/v1/conversations")?.body).toEqual({ character_id: "ch1" });
    await expect(page.getByTestId("active-character")).toHaveText("Meera");

    await page.getByRole("button", { name: "New conversation with Meera" }).click();     // a separate conversation
    await expect(page.getByText("Hello Meera, first chat")).toHaveCount(1);             // only in the list, not on the page
    await page.getByLabel("Message").fill("Second chat");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByText("Hello there, friend.").first()).toBeVisible();
    const list = page.getByRole("navigation", { name: "Conversations with Meera" });
    await expect(list.getByRole("button", { name: /Hello Meera, first chat/ })).toBeVisible();
    await expect(list.getByRole("button", { name: /Second chat/ })).toBeVisible();
    await list.getByRole("button", { name: /Hello Meera, first chat/ }).click();         // back to the first, history intact
    await expect(page.getByRole("list", { name: "Chat history" }).getByText("Hello Meera, first chat")).toBeVisible();
    await expect(page.getByRole("list", { name: "Chat history" }).getByText("Second chat")).toHaveCount(0);
  });

  test("switching characters never sends to the previous character's conversation", async ({ page }) => {
    const ch = await open(page, newChat({ chars: [newChat().chars[0], ARJUN] }), "dark", "/app/conversations?ch=ch1");
    await page.getByLabel("Message").fill("For Meera only");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByText("Hello there, friend.").first()).toBeVisible();
    const meeraConv = ch.convs[0].id;

    await page.getByRole("button", { name: "Change character" }).click();
    await page.getByRole("button", { name: "Talk to Arjun" }).click();
    await expect(page.getByTestId("active-character")).toHaveText("Arjun");
    await expect(page.getByRole("list", { name: "Chat history" }).getByText("For Meera only")).toHaveCount(0);
    await expect(page.getByRole("navigation", { name: "Conversations with Arjun" }).getByRole("button", { name: /For Meera only/ })).toHaveCount(0);
    await page.getByLabel("Message").fill("For Arjun");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByText("Hello there, friend.").first()).toBeVisible();

    const created = ch.calls.filter((c) => c.method === "POST" && c.path === "/api/v1/conversations").map((c) => (c.body as { character_id: string }).character_id);
    expect(created).toEqual(["ch1", "ch2"]);
    const streams = streamCalls(ch);
    expect(streams).toHaveLength(2);
    expect(streams[1].path).not.toContain(meeraConv);                                    // Arjun's message went to Arjun's conversation
    expect(ch.convs.find((c) => c.id === meeraConv)?.character_id).toBe("ch1");
    expect(ch.msgs[meeraConv].map((m) => m.content)).not.toContain("For Arjun");
  });

  test("changing character while a reply is being written stops it and drops the draft", async ({ page }) => {
    const ch = await open(page, newChat({ chars: [newChat().chars[0], ARJUN], mode: "hang" }), "dark", "/app/conversations?ch=ch1");
    await page.getByLabel("Message").fill("Slow question for Meera");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByRole("button", { name: "Stop" })).toBeVisible();
    await page.getByRole("button", { name: "Change character" }).click();
    await page.getByRole("button", { name: "Talk to Arjun" }).click();
    await expect(page.getByTestId("live-reply")).toHaveCount(0);
    await expect(page.getByLabel("Message")).toHaveValue("");
    await expect(page.getByRole("button", { name: "Stop" })).toHaveCount(0);
    expect(streamCalls(ch)).toHaveLength(1);                                             // nothing was re-sent to Arjun
  });

  test("opening a past conversation shows its own character", async ({ page }) => {
    const ch = newChat({ chars: [newChat().chars[0], ARJUN] });
    ch.convs.push({ id: "cA", character_id: "ch2", title: "Sea stories", created_at: "x", last_activity_at: "x", archived_at: null, learning_reviewed_at: null, learning_failure_code: null });
    ch.msgs.cA = [{ id: "mA", role: "user", content: "Tell me about the sea", status: "complete", reply_to: null, provider: null, model: null, first_token_ms: null, duration_ms: null, failure_code: null, used_memory_ids: [], created_at: "x", client_message_id: "k1" }];
    await open(page, ch, "dark", "/app/conversations?c=cA");
    await expect(page.getByTestId("active-character")).toHaveText("Arjun");
    await expect(page.getByLabel("Message")).toHaveAttribute("placeholder", "Write a message to Arjun…");
    await expect(page.getByText("Tell me about the sea")).toBeVisible();
  });
});

test.describe("conversations", () => {
  test("explains why chat is unavailable and blocks sending", async ({ page }) => {
    await open(page, newChat({ reason: "no_character" }));
    await expect(page.getByText("Describe your character first")).toBeVisible();
    await expect(page.getByLabel("Message")).toBeDisabled();
    await expect(page.getByRole("link", { name: "Open Twin Studio" })).toBeVisible();
  });

  test("chat works without a profile and says replies follow the description", async ({ page }) => {
    const ch = await open(page, newChat({ profileState: "missing" }));
    await expect(page.getByText("replies follow Meera’s description alone")).toBeVisible();
    await expect(page.getByLabel("Message")).toBeEnabled();
    await page.getByLabel("Message").fill("Hi Meera");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByText("Hello there, friend.").first()).toBeVisible();
    expect(ch.calls.some((c) => c.path.endsWith("/messages/stream"))).toBe(true);
  });

  test("sends a message, shows the reply once, and keeps it after a reload", async ({ page }) => {
    const ch = await open(page);
    await page.getByLabel("Message").fill("Hi Meera");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByText("Hello there, friend.")).toBeVisible();
    await expect(page.getByRole("list", { name: "Chat history" }).getByText("Hi Meera")).toHaveCount(1);
    await expect(page.getByText("1.2s to first word")).toBeVisible();
    await page.reload();
    await expect(page.getByText("Hello there, friend.")).toBeVisible();
    await expect(page.getByRole("list", { name: "Chat history" }).getByText("Hi Meera")).toBeVisible();
    expect(ch.calls.filter((c) => c.path.endsWith("/messages/stream"))).toHaveLength(1);
    expect((ch.calls.find((c) => c.path.endsWith("/messages/stream"))!.body as { client_message_id: string }).client_message_id.length).toBeGreaterThanOrEqual(8);
  });

  test("Enter sends, Shift+Enter adds a line", async ({ page }) => {
    await open(page);
    const box = page.getByLabel("Message");
    await box.fill("line one");
    await box.press("Shift+Enter");
    await box.type("line two");
    await expect(box).toHaveValue("line one\nline two");
    await box.press("Enter");
    await expect(page.getByText("Hello there, friend.")).toBeVisible();
  });

  test("a failed reply is marked incomplete and Try again reuses the same message without duplicating it", async ({ page }) => {
    const ch = await open(page, newChat({ mode: "fail" }));
    await page.getByLabel("Message").fill("Tell me something");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByText("The connection was interrupted before the reply finished.").first()).toBeVisible();
    await expect(page.getByText("Half of an ans")).toBeVisible();
    ch.mode = "ok";
    await page.getByRole("button", { name: "Try again" }).click();
    await expect(page.getByText("Hello there, friend.")).toBeVisible();
    await expect(page.getByText("Half of an ans")).toHaveCount(0);
    await expect(page.getByRole("list", { name: "Chat history" }).getByText("Tell me something")).toHaveCount(1);
    const keys = ch.calls.filter((c) => c.path.endsWith("/messages/stream")).map((c) => (c.body as { client_message_id: string }).client_message_id);
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBe(keys[1]);
  });

  test("Stop ends a reply that never arrives and the composer is usable again", async ({ page }) => {
    await open(page, newChat({ mode: "hang" }));
    await page.getByLabel("Message").fill("Anyone there?");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByText(/Waiting for the first words/)).toBeVisible();
    await page.getByRole("button", { name: "Stop" }).click();
    await expect(page.getByText(/Waiting for the first words/)).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Send" })).toBeDisabled(); // empty draft, but not "Stop" any more
    await page.getByLabel("Message").fill("Second try");
    await expect(page.getByRole("button", { name: "Send" })).toBeEnabled();
  });

  test("a refused request shows the specific reason, not a generic failure", async ({ page }) => {
    await open(page, newChat({ mode: "refuse", refuseCode: "model_busy" }));
    await page.getByLabel("Message").fill("Hello");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByText("The local model is busy with another job. Try again in a moment.")).toBeVisible();
  });

  test("a sample provider is labelled", async ({ page }) => {
    await open(page, newChat({ isSample: true }));
    await expect(page.getByText("Sample replies — no AI model")).toBeVisible();
  });

  test("approved memories that informed a reply are shown, and only those", async ({ page }) => {
    const ch = newChat({ memories: [{ ...sampleCandidate(), id: "mem1", status: "active", source_deleted: false, edited: false, pinned: false, superseded_by: null, updated_at: "x" }] });
    ch.candidates.push(sampleCandidate({ id: "cand9", statement: "Unapproved idea about hiking" }));
    await open(page, ch);
    await page.getByLabel("Message").fill("Chai?");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByText("Hello there, friend.")).toBeVisible();
    await expect(page.getByText("Informed by 1 approved memory")).toBeVisible();
    await expect(page.getByText("Unapproved idea about hiking")).toHaveCount(0);
  });

  test("deleting a conversation explains what happens to memories and sends the choice", async ({ page }) => {
    const ch = await open(page);
    await page.getByLabel("Message").fill("To be deleted");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByText("Hello there, friend.")).toBeVisible();
    await page.getByRole("button", { name: "Delete conversation" }).first().click();
    await expect(page.getByText("Memories you already approved are kept")).toBeVisible();
    await page.getByLabel("Also delete the memories I approved from this conversation").check();
    await page.getByRole("button", { name: "Delete conversation" }).last().click();
    await expect(page.getByText("To be deleted")).toHaveCount(0);
    expect(ch.calls.some((c) => c.method === "DELETE" && c.path === "/api/v1/conversations/c1")).toBe(true);
  });
});

test.describe("learning and memories", () => {
  test("learning is off by default, needs an explicit explanation, and review stays unavailable until then", async ({ page }) => {
    await open(page);
    await page.getByLabel("Message").fill("I really like masala chai in the mornings");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByText("Hello there, friend.")).toBeVisible();
    await expect(page.getByText("Learning from conversations is off.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Review what Madhuora learned" })).toHaveCount(0);
    await page.getByRole("link", { name: "Turn it on in Memories" }).click();
    await page.getByRole("button", { name: "Turn on…" }).click();
    await expect(page.getByText("does not retrain or change the AI model")).toBeVisible();
    await expect(page.getByRole("button", { name: "Turn on learning" })).toBeDisabled();
    await page.getByLabel("I understand, and I want to turn this on.").check();
    await page.getByRole("button", { name: "Turn on learning" }).click();
    await expect(page.getByRole("button", { name: "Turn off" })).toBeVisible();
  });

  test("review → suggestion with proof → approve → remembered; nothing is remembered before approval", async ({ page }) => {
    const ch = newChat({ learning: true, reviewResult: [sampleCandidate()] });
    await open(page, ch);
    await page.getByLabel("Message").fill("I really like masala chai in the mornings");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByText("Hello there, friend.")).toBeVisible();
    await page.getByRole("button", { name: "Review what Madhuora learned" }).click();
    await expect(page.getByText(/Reading this conversation/)).toBeVisible();
    await expect(page.getByRole("link", { name: "1 idea waiting for your review" })).toBeVisible();
    expect(ch.memories).toHaveLength(0);
    await page.getByRole("link", { name: "1 idea waiting for your review" }).click();
    await expect(page.getByText("She likes masala chai in the mornings")).toBeVisible();
    await page.getByText("Where this came from").click();
    await expect(page.getByText("“I really like masala chai in the mornings”")).toBeVisible();
    await page.getByRole("button", { name: "Remember this" }).click();
    await page.getByRole("tab", { name: /Remembered/ }).click();
    await expect(page.getByText("She likes masala chai in the mornings")).toBeVisible();
    expect(ch.memories).toHaveLength(1);
  });

  test("a conflicting memory is put to the user, who chooses", async ({ page }) => {
    const ch = newChat({ learning: true, conflictOnApprove: true });
    ch.candidates.push(sampleCandidate());
    await mockApp(page, withCharacter(true));
    await mockChat(page, ch);
    await page.goto("/app/memories");
    await page.getByRole("button", { name: "Remember this" }).click();
    await expect(page.getByText(/She drinks tea every evening/)).toBeVisible();
    expect(ch.memories).toHaveLength(0);
    await page.getByRole("button", { name: "Keep both" }).click();
    await page.getByRole("tab", { name: /Remembered/ }).click();
    await expect(page.getByText("She likes masala chai in the mornings")).toBeVisible();
    expect(ch.calls.some((c) => (c.body as { resolution?: string })?.resolution === "keep_both")).toBe(true);
  });

  test("reject, edit-before-approve and forget", async ({ page }) => {
    const ch = newChat({ learning: true });
    ch.candidates.push(sampleCandidate({ id: "a" }), sampleCandidate({ id: "b", statement: "She walks every evening" }));
    await mockApp(page, withCharacter(true));
    await mockChat(page, ch);
    await page.goto("/app/memories");
    await page.getByRole("button", { name: "That’s not right" }).first().click();
    await expect(page.getByText("She likes masala chai in the mornings")).toHaveCount(0);
    await page.getByRole("button", { name: "Edit first" }).click();
    await page.getByLabel("Edit before approving").fill("She walks for an hour each evening");
    await page.getByRole("button", { name: "Save and remember" }).click();
    await page.getByRole("tab", { name: /Remembered/ }).click();
    await expect(page.getByText("She walks for an hour each evening")).toBeVisible();
    await expect(page.getByText("Edited by you")).toBeVisible();
    await page.getByRole("button", { name: "Forget" }).click();
    await expect(page.getByText("Nothing remembered yet")).toBeVisible();
  });

  test("profile suggestion: nothing changes until accepted; the history keeps the earlier version", async ({ page }) => {
    const ch = newChat({ learning: true });
    ch.memories.push({ ...sampleCandidate(), id: "mem1", status: "active", source_deleted: false, edited: false, pinned: false, superseded_by: null, updated_at: "x" });
    await mockApp(page, withCharacter(true));
    await mockChat(page, ch);
    await page.goto("/app/memories");
    await page.getByRole("tab", { name: /Remembered/ }).click();
    await page.getByLabel("Suggest a change to the profile").selectOption("interests_and_habits");
    await page.getByRole("button", { name: "Create suggestion" }).click();
    await expect(page.getByText("Added to “Profile updates”.")).toBeVisible();
    await page.getByRole("tab", { name: /Profile updates/ }).click();
    await expect(page.getByText("Your original description stays exactly as you wrote it.")).toBeVisible();
    expect(ch.revisions).toHaveLength(0);
    await page.getByRole("button", { name: "Add to profile" }).click();
    await page.getByRole("tab", { name: /History/ }).click();
    await expect(page.getByText("Before you accepted a suggestion")).toBeVisible();
  });

  test("a memory whose conversation was deleted says its source is gone", async ({ page }) => {
    const ch = newChat({ learning: true });
    ch.memories.push({ ...sampleCandidate(), id: "mem1", supporting: [], status: "active", source_deleted: true, edited: false, pinned: false, superseded_by: null, updated_at: "x" });
    await mockApp(page, withCharacter(true));
    await mockChat(page, ch);
    await page.goto("/app/memories");
    await page.getByRole("tab", { name: /Remembered/ }).click();
    await expect(page.getByText(/conversation this came from has been deleted/)).toBeVisible();
  });
});

for (const theme of ["light", "dark"] as const) {
  for (const w of [375, 390, 768, 1280, 1440]) {
    test(`no horizontal overflow at ${w}px (${theme}) on conversations and memories`, async ({ page }) => {
      await page.setViewportSize({ width: w, height: 800 });
      const ch = newChat({ learning: true, reply: "A long reply ".repeat(30) });
      ch.candidates.push(sampleCandidate());
      await mockApp(page, withCharacter(true), { theme });
      await mockChat(page, ch);
      for (const path of ["/app/conversations", "/app/conversations?ch=ch1", "/app/memories"]) {
        await page.goto(path);
        if (path.endsWith("conversations")) {
          await expect(page.getByRole("button", { name: "Talk to Meera" })).toBeVisible();
        } else if (path.includes("ch=ch1")) {
          await page.getByLabel("Message").fill("A very long unbroken message ".repeat(8));
          await page.getByRole("button", { name: "Send" }).click();
          await expect(page.getByText(/A long reply/).first()).toBeVisible();
        } else await expect(page.getByText("She likes masala chai in the mornings")).toBeVisible();
        const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
        expect(over).toBeLessThanOrEqual(1);
      }
    });
  }
}
