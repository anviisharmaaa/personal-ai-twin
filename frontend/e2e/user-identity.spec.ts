import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { fullTwin, mockApp, newBackend } from "./mock";

// MOCKED API. These prove the UI for the signed-in USER's own optional identity (separate from a character's gender).
const base = () => newBackend({ consent: true, steps: ["welcome", "identity", "personality", "refinements"], twin: fullTwin() });
const puts = (be: ReturnType<typeof base>) => be.calls.filter((c) => c.method === "PUT" && c.path === "/api/v1/me/profile");

test.describe("your own gender and pronouns", () => {
  test("an existing account has nothing recorded, and Save is off until something changes", async ({ page }) => {
    await mockApp(page, base());
    await page.goto("/app/settings");
    const card = page.getByRole("group", { name: "About you" });
    await expect(card.getByLabel("Your gender (optional)")).toHaveValue("");
    await expect(card.getByLabel("Your pronouns (optional)")).toHaveValue("");
    await expect(card.getByLabel(/How characters refer to you/)).toHaveValue("");
    await expect(page.getByRole("heading", { name: "About you" }).locator("xpath=..").getByRole("button", { name: "Save" })).toBeDisabled();
  });

  test("offers the required options, saves them to the account and keeps them after a reload", async ({ page }) => {
    const be = base();
    await mockApp(page, be);
    await page.goto("/app/settings");
    const g = page.getByLabel("Your gender (optional)");
    await expect(g.locator("option")).toHaveText(["Not answered", "Woman", "Man", "Non-binary", "Other / custom", "Prefer not to say"]);
    await g.selectOption("woman");
    await page.getByLabel("Your pronouns (optional)").selectOption("she/her");
    await page.getByLabel(/How characters refer to you/).selectOption("feminine");
    await page.getByRole("heading", { name: "About you" }).locator("xpath=..").getByRole("button", { name: "Save" }).click();
    await expect(page.getByRole("status").filter({ hasText: "Saved." }).last()).toBeVisible();
    expect(puts(be).at(-1)?.body).toEqual({ user_gender: "woman", user_gender_custom: null, user_pronouns: "she/her", user_address_form: "feminine" });
    await page.reload();                                                         // "another device"
    await expect(page.getByLabel("Your gender (optional)")).toHaveValue("woman");
    await expect(page.getByLabel("Your pronouns (optional)")).toHaveValue("she/her");
    await expect(page.getByLabel(/How characters refer to you/)).toHaveValue("feminine");
  });

  test("Other / custom and custom pronouns take the user's own words; switching away drops the custom gender", async ({ page }) => {
    const be = base();
    await mockApp(page, be);
    await page.goto("/app/settings");
    await page.getByLabel("Your gender (optional)").selectOption("other");
    await page.getByLabel("In your own words", { exact: true }).fill("genderfluid");
    await page.getByLabel("Your pronouns (optional)").selectOption("__custom");
    await page.getByLabel("Your pronouns, in your own words").fill("xe/xem");
    const save = page.getByRole("heading", { name: "About you" }).locator("xpath=..").getByRole("button", { name: "Save" });
    await save.click();
    await expect.poll(() => puts(be).length).toBe(1);
    expect(puts(be)[0].body).toEqual({ user_gender: "other", user_gender_custom: "genderfluid", user_pronouns: "xe/xem", user_address_form: null });
    await page.getByLabel("Your gender (optional)").selectOption("prefer_not_to_say");
    await expect(page.getByLabel("In your own words", { exact: true })).toHaveCount(0);
    await save.click();
    await expect.poll(() => puts(be).length).toBe(2);
    expect(puts(be)[1].body).toMatchObject({ user_gender: "prefer_not_to_say", user_gender_custom: null });
  });

  test("a saved value can be cleared back to unspecified", async ({ page }) => {
    const be = base();
    be.userIdentity = { user_gender: "man", user_pronouns: "he/him" };
    await mockApp(page, be);
    await page.goto("/app/settings");
    await expect(page.getByLabel("Your gender (optional)")).toHaveValue("man");
    await page.getByLabel("Your gender (optional)").selectOption("");
    await page.getByLabel("Your pronouns (optional)").selectOption("");
    await page.getByRole("heading", { name: "About you" }).locator("xpath=..").getByRole("button", { name: "Save" }).click();
    await expect.poll(() => puts(be).length).toBe(1);
    expect(puts(be)[0].body).toEqual({ user_gender: null, user_gender_custom: null, user_pronouns: null, user_address_form: null });
  });

  test("onboarding can be finished without answering, and nothing about identity is sent", async ({ page }) => {
    const be = newBackend({ consent: true, steps: ["welcome"], twin: fullTwin() });
    await mockApp(page, be);
    await page.goto("/app/onboarding");
    await expect(page.getByRole("heading", { name: "Who is this twin?" })).toBeVisible();
    await expect(page.getByText("Optional: how should characters address you?")).toBeVisible();
    await page.getByRole("button", { name: "Save and continue" }).click();
    await expect(page.getByRole("heading", { name: "Character", level: 2 })).toBeVisible();
    expect(puts(be).filter((c) => JSON.stringify(c.body).includes("user_"))).toHaveLength(0);
    expect(be.steps).toContain("identity");
  });

  test("onboarding saves an optional answer once, with the identity step", async ({ page }) => {
    const be = newBackend({ consent: true, steps: ["welcome"], twin: fullTwin() });
    await mockApp(page, be);
    await page.goto("/app/onboarding");
    await page.getByText("Optional: how should characters address you?").click();
    await page.getByLabel("Your gender (optional)").selectOption("man");
    await page.getByRole("button", { name: "Save and continue" }).click();
    await expect(page.getByRole("heading", { name: "Character", level: 2 })).toBeVisible();
    expect(puts(be)).toHaveLength(1);
    expect(puts(be)[0].body).toMatchObject({ user_gender: "man", user_pronouns: null });
  });

  test("the card is usable at phone width without sideways scrolling", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 800 });
    await mockApp(page, base());
    await page.goto("/app/settings");
    await page.getByRole("heading", { name: "About you" }).scrollIntoViewIfNeeded();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.getByLabel("Your gender (optional)").selectOption("other");
    await expect(page.getByLabel("In your own words", { exact: true })).toBeVisible();
  });

  test("keyboard only: the fields are reachable and have labels (no serious axe violations)", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await mockApp(page, base());
    await page.goto("/app/settings");
    await page.getByLabel("Your gender (optional)").focus();
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Tab");
    await expect(page.getByLabel("Your pronouns (optional)")).toBeFocused();
    await page.getByLabel("Your gender (optional)").selectOption("other");
    const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
    expect(r.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => v.id)).toEqual([]);
  });
});
