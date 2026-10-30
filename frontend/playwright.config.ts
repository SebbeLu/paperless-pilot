import { defineConfig, devices } from "@playwright/test";

const PORT = 8099;

/**
 * Ende-zu-Ende-Tests gegen das echte Backend im Demo-Modus (erfundene Dokumente, regelbasiertes
 * „Modell“), das auch das gebaute Frontend ausliefert – also genau wie im Container.
 */
export default defineConfig({
  testDir: "e2e",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["github"]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    locale: "de-DE",
    timezoneId: "Europe/Berlin",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "rm -rf ../backend/.e2e-data && cd ../backend && uv run paperless-pilot",
    env: {
      PILOT_DEMO: "true",
      PILOT_DATA_DIR: ".e2e-data",
      PILOT_STATIC_DIR: "../frontend/dist",
      PILOT_PORT: String(PORT),
      PILOT_HOST: "127.0.0.1",
      PILOT_INTAKE_INTERVAL_SECONDS: "2",
    },
    url: `http://127.0.0.1:${PORT}/api/health`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
