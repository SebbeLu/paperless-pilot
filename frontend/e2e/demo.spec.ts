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

test("Text vom Bild: abschreiben, vergleichen, mit übernehmen", async ({ page }) => {
  await page.goto("/pruefen");
  const list = page.getByRole("navigation", { name: "Offene Vorschläge" });
  const applyText = page.getByRole("checkbox", { name: /Erkannten Text übernehmen/ });

  // Kontoauszug: Zahlen fehlen im alten Text – Warnung, Haken nicht gesetzt, Zahlen gelb
  await list.getByRole("button", { name: /Kontoauszug Nr\. 10/ }).click({ timeout: 60_000 });
  await expect(page.getByRole("heading", { name: "Text neu erkannt" })).toBeVisible();
  await expect(page.getByText(/Zahlen, die im bisherigen Text nicht vorkommen/)).toBeVisible();
  await expect(applyText).not.toBeChecked();
  await page.locator("body").press("t");
  await expect(page.getByText("Vom Bild abgeschrieben")).toBeVisible();
  await expect(page.locator('mark[data-diff="warn"]', { hasText: "640,00" })).toBeVisible();
  await page.getByRole("button", { name: "Vergleich schließen" }).click();

  // Kfz-Rechnung: ohne Warnung ist der Haken gesetzt, der Text geht mit nach Paperless
  await list.getByRole("button", { name: /Beitragsrechnung Kfz-Haftpflicht 2027/ }).click();
  await expect(applyText).toBeChecked();
  await page.getByRole("button", { name: /^Übernehmen/ }).click();
  await expect(page.getByText("„Beitragsrechnung Kfz-Haftpflicht 2027“ übernommen.")).toBeVisible();

  const changes = await (await page.request.get("/api/changes?document_id=7")).json();
  expect(changes[0].after.content).toContain("Jahresbeitrag: 312,40 EUR");
});
