import { test as base, expect } from "@playwright/test";

/** Jeder Test schlägt fehl, wenn im Browser Fehler auftreten (Konsole oder unbehandelt). */
const test = base.extend<{ browserErrors: string[] }>({
  browserErrors: [
    async ({ page }, use) => {
      const errors: string[] = [];
      page.on("pageerror", (error) => errors.push(error.message));
      page.on("console", (msg) => {
        if (msg.type() === "error") errors.push(msg.text());
      });
      await use(errors);
      expect(errors).toEqual([]);
    },
    { auto: true },
  ],
});

test("Übersicht zeigt Demo-Paperless und Demo-Rechner", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Übersicht" })).toBeVisible();
  await expect(page.getByText("Version Demo")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Demo-Rechner" })).toBeVisible();
});

test("Prüfen: übernehmen, rückgängig, Verlauf", async ({ page }) => {
  await page.goto("/pruefen");
  // Der Demo-Rechner liest die erfundenen Dokumente in wenigen Sekunden aus.
  await expect(page.getByLabel("Titel")).not.toHaveValue("", { timeout: 30_000 });
  await expect(page.getByTitle(/Vorschau Dokument/)).toBeVisible();

  const title = await page.getByLabel("Titel").inputValue();
  await page.keyboard.press("Enter");
  await expect(page.getByText(`„${title}“ übernommen.`)).toBeVisible();

  await page.getByRole("link", { name: "Verlauf" }).click();
  await expect(page.getByText("Übernommen").first()).toBeVisible();
  await expect(page.getByText(title).first()).toBeVisible();

  await page
    .getByRole("button", { name: /rückgängig machen/ })
    .first()
    .click();
  await expect(page.getByText("Rückgängig gemacht").first()).toBeVisible();
});

test("Regeln zeigen die Beispiel-Taxonomie verknüpft", async ({ page }) => {
  await page.goto("/regeln");
  await expect(page.getByRole("textbox", { name: "Dokumenttypen: Name" }).first()).toHaveValue(
    "Rechnung",
  );
  await expect(page.getByText("in Paperless").first()).toBeVisible();
  await expect(page.getByText(/noch nicht mit Paperless verknüpft/)).toHaveCount(0);
});

test("Rechner-Seite pausiert und setzt fort", async ({ page }) => {
  await page.goto("/rechner");
  await page.getByRole("button", { name: "Pausieren" }).click();
  await expect(page.getByText("Pausiert").first()).toBeVisible();
  await page.getByRole("button", { name: "Fortsetzen" }).click();
  await expect(page.getByRole("button", { name: "Pausieren" })).toBeVisible();
});
