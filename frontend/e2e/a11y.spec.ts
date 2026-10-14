import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { fullTwin, mockApp, newBackend, withCharacter } from "./mock";

const pages: [string, string, boolean][] = [
  ["landing", "/", false], ["sign in", "/login", false], ["register", "/register", false],
  ["dashboard", "/app", true], ["onboarding", "/app/onboarding", true], ["studio", "/app/studio", true],
  ["settings", "/app/settings", true], ["conversations", "/app/conversations", true],
];

for (const theme of ["light", "dark"] as const) {
  for (const [name, path, auth] of pages) {
    test(`axe: ${name} (${theme}) has no serious or critical violations`, async ({ page }) => {
      await page.emulateMedia({ reducedMotion: "reduce" }); // axe must not sample colours mid-fade
      await mockApp(page, newBackend({ consent: true, steps: ["welcome", "identity"], twin: fullTwin() }), { auth, theme });
      await page.goto(path);
      await page.waitForTimeout(900);
      const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
      const bad = r.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
      expect(bad.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(" | ")}`)).toEqual([]);
    });
  }
}

for (const theme of ["light", "dark"] as const) {
  test(`axe: Character tab with an interpretation (${theme}) has no serious or critical violations`, async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await mockApp(page, withCharacter(true), { theme });
    await page.goto("/app/studio");
    await page.getByRole("tab", { name: "Character" }).click();
    await expect(page.getByRole("heading", { name: "What Madhuora understood" })).toBeVisible();
    const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
    const bad = r.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(bad.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(" | ")}`)).toEqual([]);
  });
}
