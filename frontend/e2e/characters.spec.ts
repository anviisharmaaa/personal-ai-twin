import { expect, test, type Page } from "@playwright/test";
import { DESCRIPTION, mockApp, withCharacter } from "./mock";
import { mockCharacters, newChars, type CharBackend } from "./mock-characters";

// MOCKED API (mock.ts + mock-characters.ts). These prove Twin Studio UI behaviour only.
const ARJUN = "Arjun is a gruff retired sailor who speaks in short sentences and distrusts fancy words.";
const open = async (page: Page, cb: CharBackend = newChars(), url = "/app/studio") => {
  const be = withCharacter(false);
  await mockApp(page, be);
  await mockCharacters(page, cb);
  await page.goto(url);
  return { be, cb };
};

test.describe("multiple characters in Twin Studio", () => {
  test("shows your own twin and a way to add characters", async ({ page }) => {
    await open(page);
    const nav = page.getByRole("navigation", { name: "Your characters" });
    await expect(nav.getByRole("button", { name: /Anvi/ })).toHaveAttribute("aria-current", "true");
    await expect(nav.getByText("(you)")).toBeVisible();
    await expect(nav.getByRole("button", { name: "+ New character" })).toBeVisible();
  });

  test("creates a second character with its own description and opens it", async ({ page }) => {
    const { cb } = await open(page);
    await page.getByRole("button", { name: "+ New character" }).click();
    const form = page.getByRole("form", { name: "New character" });
    await form.getByRole("button", { name: "Create character" }).click();               // no name yet
    await expect(form.getByText("Give the character a name.")).toBeVisible();
    await form.getByLabel("Character’s name").fill("Arjun");
    await form.getByLabel(/Description/).fill(ARJUN);
    await form.getByRole("button", { name: "Create character" }).click();
    await expect(page).toHaveURL(/character=ch2/);
    const nav = page.getByRole("navigation", { name: "Your characters" });
    await expect(nav.getByRole("button", { name: /Arjun/ })).toHaveAttribute("aria-current", "true");
    await expect(nav.getByRole("button", { name: /Anvi/ })).toBeVisible();                // the self twin is still there
    await expect(page.getByLabel("Twin’s name")).toHaveValue("Arjun");
    await expect(page.getByText("a character you created", { exact: false })).toBeVisible();
    expect(cb.calls.find((c) => c.method === "POST" && c.path === "/api/v1/characters")?.body).toEqual({ name: "Arjun", description: ARJUN });
    await page.getByRole("tab", { name: "Character" }).click();
    await expect(page.getByLabel("Describe the person")).toHaveValue(ARJUN);              // its OWN description, not Anvi's
  });

  test("gender and pronouns are chosen at creation and sent with the new character", async ({ page }) => {
    const { cb } = await open(page);
    await page.getByRole("button", { name: "+ New character" }).click();
    const form = page.getByRole("form", { name: "New character" });
    await form.getByLabel("Character’s name").fill("Kiran");
    await form.getByRole("radio", { name: "Female", exact: true }).click();
    await expect(form.getByRole("radio", { name: "Female", exact: true })).toHaveAttribute("aria-checked", "true");
    await expect(form.getByLabel(/Pronouns/)).toHaveAttribute("placeholder", "she/her");
    await form.getByLabel(/Pronouns/).fill("she/her");
    await form.getByLabel(/Description/).fill("Kiran teases people she loves.");
    await form.getByRole("button", { name: "Create character" }).click();
    await expect(page).toHaveURL(/character=ch2/);
    expect(cb.calls.find((c) => c.method === "POST" && c.path === "/api/v1/characters")?.body)
      .toEqual({ name: "Kiran", description: "Kiran teases people she loves.", gender: "female", pronouns: "she/her" });
  });

  test("gender can be changed in the Identity tab and is saved with that character", async ({ page }) => {
    const cb = newChars({ extra: [{ id: "ch2", name: "Arjun", description: ARJUN, version: 1, portrait_url: null }], n: 2 });
    await open(page, cb, "/app/studio?character=ch2");
    await page.getByRole("radio", { name: "Male", exact: true }).click();
    await page.getByRole("button", { name: "Save changes" }).click();
    const find = () => cb.calls.find((c) => c.method === "PUT" && c.path === "/api/v1/twin");
    await expect.poll(find).toBeTruthy();
    const put = find();
    expect(put?.search).toBe("?character_id=ch2");
    expect((put?.body as { appearance: { gender?: string } }).appearance.gender).toBe("male");
  });

  test("editing a character changes only that character and the request says which one", async ({ page }) => {
    const cb = newChars({ extra: [{ id: "ch2", name: "Arjun", description: ARJUN, version: 1, portrait_url: null }], n: 2 });
    await open(page, cb, "/app/studio?character=ch2");
    await page.getByRole("tab", { name: "Character" }).click();
    await page.getByLabel("Describe the person").fill(ARJUN + " He hums sea shanties when content.");
    await page.getByRole("button", { name: "Save description" }).click();
    await expect(page.getByText("Saved.")).toBeVisible();
    const save = cb.calls.find((c) => c.method === "PUT" && c.path === "/api/v1/twin/character");
    expect(save?.search).toBe("?character_id=ch2");
    expect(cb.extra[0].description).toContain("sea shanties");
    await page.getByRole("navigation", { name: "Your characters" }).getByRole("button", { name: /Anvi/ }).click();     // back to self
    await expect(page).not.toHaveURL(/character=/);
    await page.getByRole("tab", { name: "Character" }).click();
    await expect(page.getByLabel("Describe the person")).toHaveValue(DESCRIPTION);        // self twin untouched
    expect(cb.calls.filter((c) => c.method === "PUT" && c.path === "/api/v1/twin/character" && c.search === "")).toHaveLength(0);
  });

  test("renaming a character is sent to that character, not the self twin", async ({ page }) => {
    const cb = newChars({ extra: [{ id: "ch2", name: "Arjun", description: ARJUN, version: 1, portrait_url: null }], n: 2 });
    await open(page, cb, "/app/studio?character=ch2");
    await page.getByLabel("Twin’s name").fill("Arjun Rao");
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByText("All changes saved")).toBeVisible();
    expect(cb.calls.find((c) => c.method === "PUT" && c.path === "/api/v1/twin")?.search).toBe("?character_id=ch2");
    expect(cb.extra[0].name).toBe("Arjun Rao");
  });

  test("switching characters with unsaved edits asks first instead of losing them", async ({ page }) => {
    const cb = newChars({ extra: [{ id: "ch2", name: "Arjun", description: ARJUN, version: 1, portrait_url: null }], n: 2 });
    await open(page, cb, "/app/studio?character=ch2");
    await page.getByLabel("Twin’s name").fill("Half-typed");
    await page.getByRole("navigation", { name: "Your characters" }).getByRole("button", { name: /Anvi/ }).click();
    const dialog = page.getByRole("alertdialog", { name: "Unsaved changes" });
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Keep editing" }).click();
    await expect(page.getByLabel("Twin’s name")).toHaveValue("Half-typed");
    await expect(page).toHaveURL(/character=ch2/);
  });

  test("a database that has not been migrated is explained, and the typed text is kept", async ({ page }) => {
    await open(page, newChars({ failCreate: "migration_required" }));
    await page.getByRole("button", { name: "+ New character" }).click();
    await page.getByLabel("Character’s name").fill("Arjun");
    await page.getByLabel(/Description/).fill(ARJUN);
    await page.getByRole("button", { name: "Create character" }).click();
    await expect(page.getByText(/hasn.t been upgraded/)).toBeVisible();
    await expect(page.getByLabel("Character’s name")).toHaveValue("Arjun");
    await expect(page.getByLabel(/Description/)).toHaveValue(ARJUN);
  });

  test("an unknown or someone else's character id is refused", async ({ page }) => {
    await open(page, newChars(), "/app/studio?character=not-mine");
    await expect(page.getByText("That character isn’t available.")).toBeVisible();
    await expect(page.getByLabel("Twin’s name")).toHaveCount(0);
    await page.getByRole("button", { name: "Back to your own twin" }).click();
    await expect(page.getByLabel("Twin’s name")).toHaveValue("Anvi");
  });

  test("each character has a link to talk to it", async ({ page }) => {
    const cb = newChars({ extra: [{ id: "ch2", name: "Arjun", description: ARJUN, version: 1, portrait_url: null }], n: 2 });
    await open(page, cb, "/app/studio?character=ch2");
    await expect(page.getByRole("link", { name: "Talk to Arjun" })).toHaveAttribute("href", "/app/conversations?ch=ch2");
  });
});
