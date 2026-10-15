import { expect, test } from "@playwright/test";
import { mockApp, withCharacter } from "./mock";
import { mockChat, newChat, sampleCandidate } from "./mock-chat";

// MOCKED API (see mock-chat.ts). These prove UI behaviour only, not real streaming, a real model or real RLS.
const open = async (page: import("@playwright/test").Page, ch = newChat(), theme: "light" | "dark" = "dark") => {
  await mockApp(page, withCharacter(true), { theme });
  await mockChat(page, ch);
  await page.goto("/app/conversations");
  return ch;
};

test.describe("conversations", () => {
  test("explains why chat is unavailable and blocks sending", async ({ page }) => {
    await open(page, newChat({ reason: "no_character" }));
    await expect(page.getByText("Describe your character first")).toBeVisible();
    await expect(page.getByLabel("Message")).toBeDisabled();
    await expect(page.getByRole("link", { name: "Open Twin Studio" })).toBeVisible();
  });

  test("chat works without a profile and says replies follow the description", async ({ page }) => {
    const ch = await open(page, newChat({ profileState: "missing" }));
    await expect(page.getByText("replies follow your description alone")).toBeVisible();
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
      for (const path of ["/app/conversations", "/app/memories"]) {
        await page.goto(path);
        if (path.endsWith("conversations")) {
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
