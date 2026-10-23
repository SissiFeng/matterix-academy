import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  timeout: 45000,
  // Stop within the job limit so failures still retain their traces and reports.
  globalTimeout: process.env.CI ? 10 * 60 * 1000 : undefined,
  reporter: "list",
  use: { baseURL: "http://127.0.0.1:5174", trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command:
        "cd ../.. && ACADEMY_ALLOW_DEMO=true ACADEMY_DATA_PATH=.data/e2e.sqlite ACADEMY_APP_URL=http://127.0.0.1:5174 uv run uvicorn academy.main:app --host 127.0.0.1 --port 8001",
      url: "http://127.0.0.1:8001/api/health",
      reuseExistingServer: false,
    },
    {
      command:
        "ACADEMY_API_ORIGIN=http://127.0.0.1:8001 npm run dev -- --port 5174",
      url: "http://127.0.0.1:5174",
      reuseExistingServer: false,
    },
  ],
});
