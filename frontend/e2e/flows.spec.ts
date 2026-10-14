import { expect, test } from "@playwright/test";
import { DESCRIPTION, fullTwin, mockApp, newBackend, withCharacter } from "./mock";

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

    await expect(page.getByRole("heading", { name: "Character", level: 2 })).toBeVisible();
    await expect(page.getByRole("radio")).toHaveCount(0); // no questionnaire
    await expect(page.getByRole("button", { name: "Save and continue" })).toBeDisabled(); // nothing written yet
    await page.getByLabel("Describe the person").fill(DESCRIPTION);
    await page.getByRole("button", { name: "Save and continue" }).click();

    await expect(page.getByRole("heading", { name: "Add a portrait" })).toBeVisible();
    await page.getByRole("button", { name: "Finish setup" }).click();
    await expect(page).toHaveURL(/\/app$/);
    await expect(page.getByText("Foundation ready")).toBeVisible();

    expect(be.steps).toEqual(["welcome", "identity", "personality", "refinements"]);
    const saved = be.calls.find((c) => c.path === "/api/v1/twin/character");
    expect(saved?.body).toEqual({ description: DESCRIPTION, base_version: 0 });
    expect(be.calls.some((c) => c.path === "/api/v1/twin/character/analyze")).toBe(false); // never analysed unasked
  });

  test("skipping the Character step does not mark it complete", async ({ page }) => {
    const be = newBackend({ consent: true, steps: ["welcome", "identity"], twin: fullTwin() });
    await mockApp(page, be);
    await page.goto("/app/onboarding");
    await page.getByRole("button", { name: "Skip for now" }).click();
    await expect(page.getByRole("heading", { name: "Add a portrait" })).toBeVisible();
    expect(be.steps).toEqual(["welcome", "identity"]);
  });

  test("resumes at the first incomplete step", async ({ page }) => {
    await mockApp(page, newBackend({ consent: true, steps: ["welcome", "identity"], twin: fullTwin() }));
    await page.goto("/app/onboarding");
    await expect(page.getByRole("heading", { name: "Character", level: 2 })).toBeVisible();
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

  test("appearance preferences are sent to the server and the old questionnaires are gone", async ({ page }) => {
    const be = ready();
    await mockApp(page, be);
    await page.goto("/app/studio");
    await expect(page.getByRole("tab")).toHaveText(["Identity", "Character", "Appearance"]);
    await page.getByRole("tab", { name: "Appearance" }).click();
    await page.getByRole("radio", { name: "Maroon" }).click();
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByText("All changes saved")).toBeVisible();
    const put = be.calls.find((c) => c.method === "PUT" && c.path === "/api/v1/twin");
    expect(put?.body).toMatchObject({ appearance: { background: "maroon" } });
    expect(put?.body).not.toHaveProperty("communication");
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


test.describe("Character workspace (mocked backend and mocked analysis)", () => {
  const open = async (page: import("@playwright/test").Page, be: ReturnType<typeof withCharacter>) => {
    await mockApp(page, be);
    await page.goto("/app/studio");
    await page.getByRole("tab", { name: "Character" }).click();
  };

  test("a saved description is kept as written and nothing is pre-filled for a new twin", async ({ page }) => {
    await open(page, withCharacter(false));
    await expect(page.getByLabel("Describe the person")).toHaveValue(DESCRIPTION);
    await page.unrouteAll();
    const blank = newBackend({ consent: true, steps: ["welcome", "identity"], twin: fullTwin() });
    await open(page, blank as ReturnType<typeof withCharacter>);
    await expect(page.getByLabel("Describe the person")).toHaveValue("");
    await expect(page.getByText("Not started")).toBeVisible();
    await expect(page.getByRole("button", { name: "Understand this character" })).toBeDisabled();
    await expect(page.getByText(/Write at least 40 characters/)).toBeVisible();
  });

  test("live count, over-limit error, and short text keeps analysis disabled", async ({ page }) => {
    await open(page, withCharacter(false));
    await page.getByLabel("Describe the person").fill("x".repeat(8005));
    await expect(page.getByText("That’s 5 characters over the 8,000 limit. Please shorten it.")).toBeVisible();
    await expect(page.getByText("8,005 / 8,000 characters")).toBeVisible();
    await expect(page.getByRole("button", { name: "Save description" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Understand this character" })).toBeDisabled();
  });

  test("analysing saves first, shows the interpretation, and omits unsupported sections", async ({ page }) => {
    const be = withCharacter(false);
    await open(page, be);
    await page.getByLabel("Describe the person").fill(DESCRIPTION + " She never says I love you aloud.");
    await expect(page.getByText("You have unsaved changes")).toBeVisible();
    await page.getByRole("button", { name: "Understand this character" }).click();
    await expect(page.getByRole("heading", { name: "What Madhuora understood" })).toBeVisible();
    await expect(page.getByText("Warm and teasing with close friends")).toBeVisible();
    await expect(page.getByText("Around strangers")).toBeVisible();
    await expect(page.getByText(/From your description: “goes quiet around people she has just met”/)).toBeVisible();
    await expect(page.getByRole("heading", { name: "Depending on the situation" })).toBeVisible();
    // Empty areas are not rendered, rather than shown as invented or blank content.
    await expect(page.getByRole("heading", { name: "What matters to them" })).toHaveCount(0);
    await expect(page.getByRole("status").filter({ hasText: "Interpretation updated." })).toBeVisible();
    await expect(page.getByText("Up to date with your description")).toBeVisible();
    // Saved before analysed, with the version it returned.
    const paths = be.calls.filter((c) => c.method !== "GET" && c.path.startsWith("/api/v1/twin/character")).map((c) => c.path);
    expect(paths).toEqual(["/api/v1/twin/character", "/api/v1/twin/character/analyze"]);
    expect(be.calls.find((c) => c.path.endsWith("/analyze"))?.body).toEqual({ version: 2 });
    await expect(page.getByLabel("Describe the person")).toHaveValue(DESCRIPTION + " She never says I love you aloud.");
    await expect(page.getByText(/An AI-generated interpretation of your words, made by NVIDIA \(nvidia\/test-model\)/)).toBeVisible();
  });

  test("editing marks the interpretation outdated without discarding it; regenerating refreshes it", async ({ page }) => {
    const be = withCharacter(true);
    await open(page, be);
    await expect(page.getByRole("status").filter({ hasText: "Up to date with your description" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Update the interpretation" })).toBeDisabled(); // nothing to update
    await page.getByLabel("Describe the person").fill(DESCRIPTION + " She hates being rushed.");
    await expect(page.getByText(/made from an earlier version of your description/)).toBeVisible();
    await expect(page.getByText("Warm and teasing with close friends")).toBeVisible();
    await page.getByRole("button", { name: "Save description" }).click();
    await expect(page.getByText("Saved.")).toBeVisible();
    await expect(page.getByText("Your description has changed since this was made").first()).toBeVisible();
    await page.getByRole("button", { name: "Update the interpretation" }).click();
    await expect(page.getByText("Interpretation updated.")).toBeVisible();
    await expect(page.getByText(/made from an earlier version/)).toHaveCount(0);
  });

  test("a failed analysis keeps the previous interpretation and the user's text, and can be retried", async ({ page }) => {
    const be = withCharacter(true, { analyze: "timeout" });
    await open(page, be);
    await page.getByLabel("Describe the person").fill(DESCRIPTION + " Extra detail.");
    await page.getByRole("button", { name: "Update the interpretation" }).click();
    await expect(page.getByRole("alert").filter({ hasText: "took too long" })).toBeVisible();
    await expect(page.getByText("Your description is saved. You can retry.")).toBeVisible();
    await expect(page.getByText("Warm and teasing with close friends")).toBeVisible(); // last good profile still there
    await expect(page.getByText(/made from an earlier version of your description/)).toBeVisible(); // and not called current
    await expect(page.getByLabel("Describe the person")).toHaveValue(DESCRIPTION + " Extra detail.");
    be.analyze = "ok";
    await page.getByRole("button", { name: "Update the interpretation" }).click();
    await expect(page.getByText("Interpretation updated.")).toBeVisible();
  });

  test("repeated clicks send one analysis request", async ({ page }) => {
    const be = withCharacter(false, { analyzeDelayMs: 600 });
    await open(page, be);
    const btn = page.getByRole("button", { name: "Understand this character" });
    await btn.click();
    await btn.click({ force: true, timeout: 500 }).catch(() => undefined);
    await expect(page.getByRole("heading", { name: "What Madhuora understood" })).toBeVisible();
    expect(be.calls.filter((c) => c.path.endsWith("/analyze"))).toHaveLength(1);
  });

  test("without consent analysis is disabled and explains why; the description can still be saved", async ({ page }) => {
    await open(page, withCharacter(false, { consent: false }));
    await expect(page.getByRole("button", { name: "Understand this character" })).toBeDisabled();
    await expect(page.getByText("AI processing consent is needed before Madhuora can read this.")).toBeVisible();
    await page.getByLabel("Describe the person").fill(DESCRIPTION + " More.");
    await expect(page.getByRole("button", { name: "Save description" })).toBeEnabled();
  });

  test("when the server has no AI configured the UI says so instead of faking a result", async ({ page }) => {
    const be = withCharacter(false, { aiConfigured: false });
    await open(page, be);
    await expect(page.getByText(/AI analysis isn’t set up on this server yet/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Understand this character" })).toBeDisabled();
    await expect(page.getByRole("heading", { name: "What Madhuora understood" })).toHaveCount(0);
  });

  test("unsaved description edits are protected when leaving", async ({ page }) => {
    await open(page, withCharacter(false));
    await page.getByLabel("Describe the person").fill(DESCRIPTION + " Changed.");
    await page.getByRole("link", { name: "Settings" }).click();
    await expect(page.getByRole("alertdialog", { name: "Unsaved changes" })).toBeVisible();
    await page.getByRole("button", { name: "Keep editing" }).click();
    await expect(page.getByLabel("Describe the person")).toHaveValue(DESCRIPTION + " Changed.");
  });

  test("a save conflict from another tab is explained, not silently overwritten", async ({ page }) => {
    const be = withCharacter(false);
    await open(page, be);
    await page.getByLabel("Describe the person").fill(DESCRIPTION + " Mine.");
    be.character.version = 5; // someone else saved meanwhile
    be.character.description = "Their version";
    await page.getByRole("button", { name: "Save description" }).click();
    await expect(page.getByText(/changed in another tab or device/)).toBeVisible();
    await expect(page.getByLabel("Describe the person")).toHaveValue(DESCRIPTION + " Mine.");
  });

  test("consent text names the provider that is actually configured, never a hard-coded one", async ({ page }) => {
    await mockApp(page, withCharacter(false, { consent: false }));
    await page.goto("/app/settings");
    await expect(page.getByText("AI provider on this server: NVIDIA")).toBeVisible();
    await expect(page.getByText(/NVIDIA's hosted API/)).toBeVisible();
    await expect(page.getByText(/OpenAI/)).toHaveCount(0);
  });

  test("a development provider shows a fictional-text-only warning next to the action", async ({ page }) => {
    await open(page, withCharacter(false));
    await expect(page.getByText(/Development AI provider \(NVIDIA\)/)).toBeVisible();
    await expect(page.getByText(/fictional or non-sensitive text only/)).toBeVisible();
  });

  test("a local Ollama provider shows the local notice, not the fictional-only warning, and says what is not local", async ({ page }) => {
    await open(page, withCharacter(false, { provider: "ollama", analyzeDelayMs: 300 }));
    await expect(page.getByText(/Analysed by a model running on this computer \(Ollama\)/)).toBeVisible();
    await expect(page.getByText(/Development AI provider/)).toHaveCount(0);
    await page.getByRole("button", { name: "Understand this character" }).click();
    await expect(page.getByText(/with the local model… this can take a minute or two/)).toBeVisible();
    await expect(page.getByText(/made by Ollama \(local model\)/)).toBeVisible();
  });

  test("Ollama not running is explained plainly and the previous interpretation stays", async ({ page }) => {
    const be = withCharacter(true, { provider: "ollama", analyze: "local_unavailable" });
    await open(page, be);
    await page.getByLabel("Describe the person").fill(DESCRIPTION + " Extra detail.");
    await page.getByRole("button", { name: "Update the interpretation" }).click();
    await expect(page.getByRole("alert").filter({ hasText: "Ollama isn't running" })).toBeVisible();
    await expect(page.getByText("Warm and teasing with close friends")).toBeVisible();
    await expect(page.getByLabel("Describe the person")).toHaveValue(DESCRIPTION + " Extra detail.");
  });

  test("sample mode is labelled as a sample and never described as AI-generated", async ({ page }) => {
    const be = withCharacter(false, { provider: "mock" });
    await open(page, be);
    await expect(page.getByText(/Development AI provider/)).toHaveCount(0); // nothing leaves the server
    await page.getByRole("button", { name: "Understand this character" }).click();
    await expect(page.getByText("Sample output, not an AI reading.")).toBeVisible();
    await expect(page.getByText(/An AI-generated interpretation/)).toHaveCount(0);
  });

  test("when the free provider's allowance is used up the user is told, and nothing is overwritten", async ({ page }) => {
    const be = withCharacter(true, { analyze: "quota_exhausted" });
    await open(page, be);
    await page.getByLabel("Describe the person").fill(DESCRIPTION + " More detail.");
    await page.getByRole("button", { name: "Update the interpretation" }).click();
    await expect(page.getByText(/free allowance is used up/)).toBeVisible();
    await expect(page.getByLabel("Describe the person")).toHaveValue(DESCRIPTION + " More detail.");
    await expect(page.getByText("Warm and teasing with close friends")).toBeVisible(); // last good profile kept
    expect(be.calls.filter((c) => c.path.endsWith("/analyze"))).toHaveLength(1); // no automatic retry
  });

  test("consent can be given again after withdrawal", async ({ page }) => {
    const be = withCharacter(false, { consent: false });
    await mockApp(page, be);
    await page.goto("/app/settings");
    await page.getByRole("button", { name: "Agree to AI processing" }).click();
    await expect(page.getByText(/You agreed to external AI processing/)).toBeVisible();
    expect(be.consent).toBe(true);
  });
});
