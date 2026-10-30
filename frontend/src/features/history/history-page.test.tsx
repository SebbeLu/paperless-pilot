import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { renderApp } from "@/test/render";
import { change, lookups } from "@/test/review-fixtures";
import { server } from "@/test/server";
import { describe as describeChange } from "./history-page";

function serve(pages: ReturnType<typeof change>[][], options: { conflict?: boolean } = {}) {
  const requests: URLSearchParams[] = [];
  const reverts: { id: number; force: boolean }[] = [];
  let conflict = options.conflict ?? false;
  server.use(
    http.get("*/api/paperless/lookups", () => HttpResponse.json(lookups)),
    http.get("*/api/changes", ({ request }) => {
      const params = new URL(request.url).searchParams;
      requests.push(params);
      return HttpResponse.json(params.get("before_id") ? (pages[1] ?? []) : pages[0]);
    }),
    http.post("*/api/changes/:id/revert", async ({ params, request }) => {
      const { force } = (await request.json()) as { force: boolean };
      if (conflict && !force) {
        conflict = false;
        return HttpResponse.json(
          {
            detail: "Das Dokument wurde seitdem in Paperless geändert (Titel)",
            conflict: ["Titel"],
          },
          { status: 409 },
        );
      }
      reverts.push({ id: Number(params.id), force });
      return HttpResponse.json(change(99, { kind: "revert" }));
    }),
  );
  return { requests, reverts };
}

describe("Verlauf", () => {
  it("zeigt Änderungen mit Namen statt IDs", async () => {
    serve([[change(1)]]);
    renderApp("/verlauf");

    expect(await screen.findByText("Übernommen")).toBeInTheDocument();
    expect(await screen.findByText("Bescheinigung")).toBeInTheDocument();
    expect(screen.getByText("Rechnung")).toBeInTheDocument();
    expect(screen.getByText("o_Online-Shops")).toBeInTheDocument();
    expect(screen.getByText("Muster Möbel")).toBeInTheDocument();
    expect(screen.getByText("07.10.2026")).toBeInTheDocument();
    expect(screen.getByText("#42, Alex, Einkauf")).toBeInTheDocument();
  });

  it("macht rückgängig und bestätigt Konflikte", async () => {
    const backend = serve([[change(1)]], { conflict: true });
    renderApp("/verlauf");

    await userEvent.click(await screen.findByRole("button", { name: /rückgängig machen/ }));
    expect(await screen.findByText(/seitdem in Paperless geändert \(Titel\)/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Trotzdem zurücksetzen" }));

    await waitFor(() => expect(backend.reverts).toEqual([{ id: 1, force: true }]));
  });

  it("zeigt Rücknahmen ohne Knopf und blättert", async () => {
    const page = Array.from({ length: 50 }, (_, i) =>
      change(100 - i, { reverted_by: i === 0 ? 7 : null }),
    );
    const backend = serve([page, [change(3, { kind: "revert" })]]);
    renderApp("/verlauf");

    expect(await screen.findByText(/später rückgängig gemacht/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Ältere laden" }));

    expect(await screen.findByText("Rückgängig gemacht")).toBeInTheDocument();
    expect(backend.requests[1]?.get("before_id")).toBe("51");
  });

  it("meldet Fehler und zeigt den leeren Zustand", async () => {
    serve([[]]);
    renderApp("/verlauf");
    expect(await screen.findByText(/Noch keine Änderungen/)).toBeInTheDocument();
  });

  it("zeigt Fehler beim Rückgängigmachen", async () => {
    serve([[change(1)]]);
    server.use(
      http.post("*/api/changes/:id/revert", () =>
        HttpResponse.json({ detail: "kaputt" }, { status: 500 }),
      ),
    );
    renderApp("/verlauf");

    await userEvent.click(await screen.findByRole("button", { name: /rückgängig machen/ }));
    expect(await screen.findByText("kaputt")).toBeInTheDocument();
  });

  it("meldet Ladefehler", async () => {
    server.use(
      http.get("*/api/changes", () => HttpResponse.json({ detail: "DB weg" }, { status: 500 })),
    );
    renderApp("/verlauf");
    expect(await screen.findByText("DB weg")).toBeInTheDocument();
  });
});

describe("describe", () => {
  it("zeigt nur geänderte Felder und kommt ohne Auswahllisten aus", () => {
    const c = change(1);
    expect(describeChange(c.before, c.before, undefined)).toEqual([]);
    expect(describeChange(c.before, c.after, undefined).map((d) => d.label)).toEqual([
      "Titel",
      "Dokumenttyp",
      "Absender",
      "Datum",
      "Tags",
    ]);
  });
});
