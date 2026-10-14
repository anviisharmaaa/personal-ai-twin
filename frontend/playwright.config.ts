import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  fullyParallel: true,
  reporter: [["list"]],
  use: { baseURL: "http://127.0.0.1:5173", trace: "retain-on-failure" },
  webServer: {
    command: "npx vite --port 5173 --host 127.0.0.1",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: true,
    env: { VITE_SUPABASE_URL: "https://mock.supabase.co", VITE_SUPABASE_ANON_KEY: "test-key", VITE_API_URL: "http://localhost:8000" },
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
