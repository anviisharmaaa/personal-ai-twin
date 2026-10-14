import { expect, test } from "@playwright/test";
import { fullTwin, mockApp, newBackend } from "./mock";

test.describe("auth gate and sign-in messages", () => {
  test("signed-out users are sent to sign-in", async ({ page }) => {
    await mockApp(page, newBackend(), { auth: false });
    await page.goto("/app/studio");
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
  });

  test("wrong credentials give a generic message", async ({ page }) => {
    await mockApp(page, newBackend(), {
      auth: false,
      supabase: (r) => r.fulfill({ status: 400, json: { error: "invalid_grant", error_description: "Invalid login credentials" }, headers: { "access-control-allow-origin": "*" } }),
    });
    await page.goto("/login");
    await page.getByLabel("Email").fill("a@b.co");
    await page.getByLabel("Password").fill("wrong-password");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByText("That email and password don’t match.")).toBeVisible();
  });

  test("sign-up never reveals whether an address is registered", async ({ page }) => {
    for (const status of [200, 422]) {
      await mockApp(page, newBackend(), {
        auth: false,
        supabase: (r) => r.fulfill({ status, json: status === 200 ? { id: "x", email: "a@b.co" } : { code: 422, msg: "User already registered" }, headers: { "access-control-allow-origin": "*" } }),
      });
      await page.goto("/register");
      await page.getByLabel("Email").fill("a@b.co");
      await page.getByLabel("Password").fill("a-long-enough-password");
      await page.getByRole("button", { name: "Create account" }).click();
      await expect(page.getByText("If that address can be used, an email is on its way.")).toBeVisible();
      await page.unrouteAll();
    }
  });

  test("validation is inline and accessible", async ({ page }) => {
    await mockApp(page, newBackend(), { auth: false });
    await page.goto("/register");
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page.getByRole("alert").filter({ hasText: "valid email" })).toBeVisible();
    await expect(page.getByLabel("Email")).toHaveAttribute("aria-invalid", "true");
  });
});

test.describe("guided onboarding", () => {
  test("new user completes setup; progress is only recorded by real saves", async ({ page }) => {
    const be = newBackend();
    await mockApp(page, be);
    await page.goto("/app");
    await expect(page).toHaveURL(/\/app\/onboarding$/);

    const agree = page.getByRole("button", { name: "Agree and continue" });
    await expect(agree).toBeDisabled();
    await page.getByRole("checkbox").check();
    await agree.click();

    await expect(page.getByRole("heading", { name: "Who is this twin?" })).toBeVisible();
    await page.getByRole("button", { name: "Save and continue" }).click(); // empty name
    await expect(page.getByText("Give your twin a name.")).toBeVisible();
    expect(be.steps).toEqual(["welcome"]);
    await page.getByLabel("Twin’s name").fill("Anvi");
    await page.getByRole("button", { name: "Save and continue" }).click();

    await expect(page.getByRole("heading", { name: "How does your twin communicate?" })).toBeVisible();
    await page.getByRole("radio", { name: "Warm" }).click();
    await page.getByRole("checkbox", { name: "Family" }).click();
    await page.getByRole("button", { name: "Save and continue" }).click();

    await expect(page.getByRole("heading", { name: "Add a portrait" })).toBeVisible();
    await page.getByRole("button", { name: "Finish setup" }).click();
    await expect(page).toHaveURL(/\/app$/);
    await expect(page.getByText("Foundation ready")).toBeVisible();

    expect(be.steps).toEqual(["welcome", "identity", "personality", "refinements"]);
    const personality = be.calls.find((c) => c.path === "/api/v1/twin/personality");
    expect(personality?.body).toEqual({ answers: { tone: "warm", values: ["family"] } });
  });

  test("resumes at the first incomplete step", async ({ page }) => {
    await mockApp(page, newBackend({ consent: true, steps: ["welcome", "identity"], twin: fullTwin({ personality: {} }) }));
    await page.goto("/app/onboarding");
    await expect(page.getByRole("heading", { name: "How does your twin communicate?" })).toBeVisible();
  });

  test("steps that don't exist yet are shown as locked, not clickable", async ({ page }) => {
    await mockApp(page, newBackend({ consent: true, steps: ["welcome"] }));
    await page.goto("/app/onboarding");
    await expect(page.getByText("Your first conversation")).toBeVisible();
    await expect(page.getByRole("button", { name: /first conversation/i })).toHaveCount(0);
  });
});

test.describe("Twin Studio", () => {
  const ready = () => newBackend({ consent: true, steps: ["welcome", "identity", "personality"], twin: fullTwin() });

  test("unsaved-changes guard, discard and save", async ({ page }) => {
    const be = ready();
    await mockApp(page, be);
    await page.goto("/app/studio");
    await expect(page.getByText("No changes")).toBeVisible();
    await page.getByLabel("Twin’s name").fill("Anvi Sharma");
    await expect(page.getByText("Unsaved changes")).toBeVisible();

    await page.getByRole("link", { name: "Settings" }).click();
    await expect(page.getByRole("alertdialog", { name: "Unsaved changes" })).toBeVisible();
    await page.getByRole("button", { name: "Keep editing" }).click();
    await expect(page).toHaveURL(/\/app\/studio$/);

    await page.getByRole("button", { name: "Discard" }).click();
    await expect(page.getByLabel("Twin’s name")).toHaveValue("Anvi");

    await page.getByLabel("Twin’s name").fill("Anvi Sharma");
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByText("All changes saved")).toBeVisible();
    expect(be.calls.filter((c) => c.method === "PUT" && c.path === "/api/v1/twin")).toHaveLength(1);
  });

  test("a failed save keeps the user's edits and says so", async ({ page }) => {
    const be = ready();
    be.failTwinSave = true;
    await mockApp(page, be);
    await page.goto("/app/studio");
    await page.getByLabel("Twin’s name").fill("Edited name");
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByText("Data service error. Please try again.")).toBeVisible();
    await expect(page.getByLabel("Twin’s name")).toHaveValue("Edited name");
    await expect(page.getByText("Unsaved changes")).toHaveCount(0); // replaced by the error, edits remain
    await expect(page.getByRole("button", { name: "Save changes" })).toBeEnabled();
  });

  test("communication and appearance preferences are sent to the server", async ({ page }) => {
    const be = ready();
    await mockApp(page, be);
    await page.goto("/app/studio");
    await page.getByRole("tab", { name: "Communication" }).click();
    await page.getByRole("radio", { name: "Short" }).click();
    await page.getByRole("tab", { name: "Appearance" }).click();
    await page.getByRole("radio", { name: "Maroon" }).click();
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByText("All changes saved")).toBeVisible();
    const put = be.calls.find((c) => c.method === "PUT" && c.path === "/api/v1/twin");
    expect(put?.body).toMatchObject({ communication: { length: "short" }, appearance: { background: "maroon" } });
  });

  test("portrait: crop dialog, permission gate for another person's portrait, upload and delete", async ({ page }) => {
    const be = ready();
    await mockApp(page, be);
    await page.goto("/app/studio");
    await page.getByRole("tab", { name: "Appearance" }).click();
    const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64");
    await page.getByLabel("Choose portrait file").setInputFiles({ name: "me.png", mimeType: "image/png", buffer: png });
    const dialog = page.getByRole("dialog", { name: "Crop portrait" });
    await expect(dialog).toBeVisible();
    await dialog.getByLabel("This portrait shows someone other than me").check();
    await expect(dialog.getByRole("button", { name: "Save portrait" })).toBeDisabled();
    await dialog.getByLabel(/I have this person's permission/).check();
    await dialog.getByLabel("This portrait shows someone other than me").uncheck();
    await expect(dialog.getByLabel(/I have this person's permission/)).toHaveCount(0);

    await expect(dialog.getByRole("button", { name: "Save portrait" })).toBeEnabled();
    await dialog.getByRole("button", { name: "Save portrait" }).click();
    await expect(dialog).toHaveCount(0);
    const up = be.calls.find((c) => c.method === "POST" && c.path === "/api/v1/twin/portrait");
    expect(up?.body).toBe("<multipart>");
    await expect(page.getByAltText("Portrait of Anvi").first()).toBeVisible();

    await page.getByRole("button", { name: "Delete portrait" }).click();
    await page.getByRole("alertdialog", { name: "Delete portrait" }).getByRole("button", { name: "Delete" }).click();
    await expect(page.getByAltText("Portrait of Anvi")).toHaveCount(0);
    expect(be.calls.some((c) => c.method === "DELETE" && c.path === "/api/v1/twin/portrait")).toBe(true);
  });

  test("an unsupported file is rejected before upload", async ({ page }) => {
    await mockApp(page, ready());
    await page.goto("/app/studio");
    await page.getByRole("tab", { name: "Appearance" }).click();
    await page.getByLabel("Choose portrait file").setInputFiles({ name: "x.gif", mimeType: "image/gif", buffer: Buffer.from("GIF89a") });
    await expect(page.getByText("Please choose a JPEG, PNG or WebP image.")).toBeVisible();
  });
});

test.describe("honest availability", () => {
  for (const [path, title] of [["conversations", "Conversations"], ["memories", "Memories"], ["voice", "Voice"], ["automations", "Automations"]] as const) {
    test(`${title} says it is not available and offers no fake controls`, async ({ page }) => {
      await mockApp(page, newBackend({ consent: true, steps: ["welcome", "identity", "personality"], twin: fullTwin() }));
      await page.goto(`/app/${path}`);
      await expect(page.getByRole("heading", { name: title, level: 1 })).toBeVisible();
      await expect(page.getByText("Not available yet").first()).toBeVisible();
      await expect(page.getByRole("main").getByRole("button")).toHaveCount(0);
    });
  }

  test("settings does not offer export or deletion buttons", async ({ page }) => {
    await mockApp(page, newBackend({ consent: true, steps: ["welcome"], twin: fullTwin() }));
    await page.goto("/app/settings");
    await expect(page.getByRole("button", { name: /delete|export/i })).toHaveCount(0);
    await expect(page.getByText("Not available yet")).toHaveCount(3);
  });

  test("consent can be withdrawn", async ({ page }) => {
    const be = newBackend({ consent: true, steps: ["welcome"], twin: fullTwin() });
    await mockApp(page, be);
    await page.goto("/app/settings");
    await page.getByRole("button", { name: "Withdraw consent" }).click();
    await expect(page.getByText("You haven’t agreed to external AI processing")).toBeVisible();
    expect(be.consent).toBe(false);
  });
});

test.describe("responsive shell and theme", () => {
  test("mobile drawer navigates and closes", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await mockApp(page, newBackend({ consent: true, steps: ["welcome", "identity", "personality"], twin: fullTwin() }));
    await page.goto("/app");
    await page.getByRole("button", { name: "Open menu" }).click();
    const menu = page.getByRole("dialog", { name: "Menu" });
    await menu.getByRole("link", { name: "Twin Studio" }).click();
    await expect(page).toHaveURL(/\/app\/studio$/);
    await expect(menu).toHaveCount(0);
  });

  test("sidebar collapses to 72px and expands to 248px", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await mockApp(page, newBackend({ consent: true, steps: ["welcome", "identity", "personality"], twin: fullTwin() }));
    await page.goto("/app");
    const aside = page.locator("aside");
    await expect.poll(async () => (await aside.boundingBox())?.width).toBe(248);
    await page.getByRole("button", { name: "Collapse sidebar" }).click();
    await expect.poll(async () => (await aside.boundingBox())?.width).toBe(72);
    await page.getByRole("button", { name: "Expand sidebar" }).click();
    await expect.poll(async () => (await aside.boundingBox())?.width).toBe(248);
  });

  test("theme toggle switches and persists", async ({ page }) => {
    await mockApp(page, newBackend({ consent: true, steps: ["welcome", "identity", "personality"], twin: fullTwin() }), { theme: "dark" });
    await page.goto("/app");
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await page.getByRole("button", { name: "Switch to light theme" }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  });

  test("reduced motion stops ambient animation", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await mockApp(page, newBackend(), { auth: false });
    await page.goto("/");
    const name = await page.evaluate(() => getComputedStyle(document.querySelector(".atelier-bg")!, "::before").animationName);
    expect(name).toBe("none");
  });

  test("offline banner appears when the connection drops", async ({ page, context }) => {
    await mockApp(page, newBackend({ consent: true, steps: ["welcome", "identity", "personality"], twin: fullTwin() }));
    await page.goto("/app");
    await context.setOffline(true);
    await expect(page.getByText(/You are offline/)).toBeVisible();
    await context.setOffline(false);
    await expect(page.getByText(/You are offline/)).toHaveCount(0);
  });
});
