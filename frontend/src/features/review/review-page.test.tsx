import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { renderApp } from "@/test/render";
import { detail, reviewHandlers, suggestion } from "@/test/review-fixtures";
import { healthyStatus, server, statusHandler } from "@/test/server";
import { formatDate, nameOf } from "./review-form";

function setup(items = [suggestion(1), suggestion(2)], options = {}) {
  const { handlers, backend } = reviewHandlers(items, options);
  server.use(...handlers);
  renderApp("/pruefen");
  return backend;
}

const form = () =>
  screen.getByRole("button", { name: /Übernehmen/ }).closest("form") as HTMLElement;

describe("Prüfen", () => {
  it("zeigt Vorschlag, bisherige Werte, Belege und Vorschau", async () => {
    setup();

    expect(await screen.findByText("2 Vorschläge offen · unsichere zuerst")).toBeInTheDocument();
    expect(await screen.findByLabelText("Dokumenttyp")).toHaveValue("10");
    expect(screen.getByText("bisher: Bescheinigung")).toBeInTheDocument();
    expect(screen.getByText("bisher: o_Online-Shops")).toBeInTheDocument();
    expect(screen.getByText("bisher: 07.10.2026")).toBeInTheDocument();
    expect(screen.getByText("„den 12.09.2025“")).toBeInTheDocument();
    expect(screen.getByText("im Text nicht gefunden: Alex")).toBeInTheDocument();
    expect(screen.getByLabelText("Absender")).toHaveValue("91");
    expect(
      within(screen.getByLabelText("Absender")).queryByText("o_Online-Shops"),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Alex" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTitle("Vorschau Dokument 701")).toHaveAttribute(
      "src",
      "/api/documents/701/preview",
    );
    expect(screen.getByText(/1 von 2 · gemma4:26b auf Mac · 23 s/)).toBeInTheDocument();
  });

  it("übernimmt korrigierte Werte und springt zum nächsten Vorschlag", async () => {
    const backend = setup();
    const title = await screen.findByLabelText("Titel");

    await userEvent.clear(title);
    await userEvent.type(title, "Schreibtischstuhl");
    await userEvent.click(screen.getByRole("button", { name: "Kim" }));
    await userEvent.selectOptions(screen.getByLabelText("Lebensbereich"), "31");
    await userEvent.clear(screen.getByLabelText("Datum"));
    await userEvent.click(screen.getByRole("button", { name: /Übernehmen/ }));

    await waitFor(() => expect(backend.accepted).toHaveLength(1));
    expect(backend.accepted[0]).toEqual({
      id: 1,
      body: {
        force: false,
        values: expect.objectContaining({
          title: "Schreibtischstuhl",
          person_tag_ids: [20, 21],
          area_tag_id: 31,
          created: null,
        }),
      },
    });
    expect(await screen.findByDisplayValue("Bürostuhl 2")).toBeInTheDocument();
  });

  it("legt einen neuen Absender an oder wählt einen vorhandenen", async () => {
    const backend = setup([
      suggestion(1, {
        proposed: {
          ...suggestion(1).proposed,
          correspondent_id: null,
          new_correspondent: "Neu GmbH",
        },
      }),
    ]);
    const select = await screen.findByLabelText("Absender");
    expect(select).toHaveValue("new");
    const name = screen.getByLabelText("Name des neuen Absenders");
    await userEvent.clear(name);
    await userEvent.type(name, "Neu und Co");

    await userEvent.click(screen.getByRole("button", { name: /Übernehmen/ }));
    await waitFor(() => expect(backend.accepted).toHaveLength(1));
    expect(backend.accepted[0]?.body.values).toMatchObject({
      correspondent_id: null,
      new_correspondent: "Neu und Co",
    });
  });

  it("wechselt zwischen vorhandenem und neuem Absender", async () => {
    setup();
    const select = await screen.findByLabelText("Absender");

    await userEvent.selectOptions(select, "new");
    expect(screen.getByLabelText("Name des neuen Absenders")).toHaveValue("");
    await userEvent.selectOptions(select, "92");
    expect(screen.queryByLabelText("Name des neuen Absenders")).not.toBeInTheDocument();
    await userEvent.selectOptions(select, "");
    await userEvent.selectOptions(screen.getByLabelText("Dokumenttyp"), "");
    expect(screen.getByLabelText("Dokumenttyp")).toHaveValue("");
  });

  it("bedient sich komplett mit der Tastatur", async () => {
    const backend = setup([suggestion(1), suggestion(2), suggestion(3)]);
    await screen.findByDisplayValue("Bürostuhl 1");

    await userEvent.keyboard("j");
    expect(await screen.findByDisplayValue("Bürostuhl 2")).toBeInTheDocument();
    await userEvent.keyboard("k");
    expect(await screen.findByDisplayValue("Bürostuhl 1")).toBeInTheDocument();

    await userEvent.keyboard("e");
    expect(document.activeElement).toHaveAccessibleName("Alex");
    await userEvent.keyboard("{Escape}");

    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(backend.accepted.map((a) => a.id)).toEqual([1]));
    expect(await screen.findByDisplayValue("Bürostuhl 2")).toBeInTheDocument();

    await userEvent.keyboard("r");
    await waitFor(() => expect(backend.rejected).toEqual([2]));
    expect(await screen.findByDisplayValue("Bürostuhl 3")).toBeInTheDocument();

    await userEvent.keyboard("?");
    expect(screen.getByText("Ins erste unsichere Feld springen")).toBeInTheDocument();
    await userEvent.keyboard("{Control>}j{/Control}");
    expect(screen.getByDisplayValue("Bürostuhl 3")).toBeInTheDocument();
  });

  it("macht die letzte Übernahme mit Z rückgängig", async () => {
    const backend = setup();
    await screen.findByDisplayValue("Bürostuhl 1");

    await userEvent.keyboard("{Enter}");
    expect(await screen.findByText("„Bürostuhl 1“ übernommen.")).toBeInTheDocument();
    await screen.findByDisplayValue("Bürostuhl 2");
    await userEvent.keyboard("z");

    await waitFor(() => expect(backend.reverted).toEqual([101]));
    expect(await screen.findByDisplayValue("Bürostuhl 1")).toBeInTheDocument();
    expect(screen.queryByText("„Bürostuhl 1“ übernommen.")).not.toBeInTheDocument();
    await userEvent.keyboard("z"); // nichts mehr rückgängig zu machen
    expect(backend.reverted).toHaveLength(1);
  });

  it("zeigt Fehler beim Rückgängigmachen", async () => {
    setup();
    server.use(
      http.post("*/api/changes/:id/revert", () =>
        HttpResponse.json({ detail: "Paperless weg" }, { status: 503 }),
      ),
    );
    await screen.findByDisplayValue("Bürostuhl 1");

    await userEvent.keyboard("{Enter}");
    await userEvent.click(await screen.findByRole("button", { name: /Rückgängig/ }));
    expect(await screen.findByText("Paperless weg")).toBeInTheDocument();
  });

  it("Enter im Eingabefeld übernimmt, Tasten im Feld blättern nicht", async () => {
    const backend = setup();
    const title = await screen.findByLabelText("Titel");

    await userEvent.type(title, " jk");
    expect(title).toHaveValue("Bürostuhl 1 jk");
    await userEvent.type(title, "{Enter}");

    await waitFor(() => expect(backend.accepted[0]?.body.values.title).toBe("Bürostuhl 1 jk"));
  });

  it("zeigt Konflikte und übernimmt auf Wunsch trotzdem", async () => {
    const backend = setup([suggestion(1)], { conflictOnce: true });
    await screen.findByDisplayValue("Bürostuhl 1");

    await userEvent.click(screen.getByRole("button", { name: /Übernehmen/ }));
    expect(
      await screen.findByText(/seit dem Auslesen in Paperless geändert \(Titel\)/),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Trotzdem übernehmen" }));

    await waitFor(() => expect(backend.accepted[0]?.body.force).toBe(true));
  });

  it("warnt, wenn das Dokument inzwischen geändert wurde, und liest auf Wunsch neu aus", async () => {
    const item = suggestion(1);
    const { handlers, backend } = reviewHandlers([item]);
    server.use(...handlers);
    // Später registrierte Handler haben Vorrang
    server.use(
      http.get("*/api/suggestions/:id", () =>
        HttpResponse.json(detail(item, { changed_since: ["Absender"] })),
      ),
    );
    renderApp("/pruefen");

    expect(
      await screen.findByText("Seit dem Auslesen in Paperless geändert: Absender."),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Neu auslesen" }));
    await waitFor(() => expect(backend.reextracted).toEqual([1]));
  });

  it("wählt per Liste und zeigt Fehler verständlich", async () => {
    setup();
    server.use(
      http.post("*/api/suggestions/:id/reject", () =>
        HttpResponse.json({ detail: "Paperless nicht erreichbar" }, { status: 503 }),
      ),
    );
    const list = await screen.findByRole("navigation", { name: "Offene Vorschläge" });

    await userEvent.click(within(list).getByText("Bürostuhl 2"));
    expect(await screen.findByDisplayValue("Bürostuhl 2")).toBeInTheDocument();
    expect(within(list).getAllByLabelText("1 Hinweise")).toHaveLength(2);
    await userEvent.click(within(form()).getByRole("button", { name: /Verwerfen/ }));
    expect(await screen.findByText("Paperless nicht erreichbar")).toBeInTheDocument();
  });

  it("zeigt den leeren Zustand mit Hinweis auf die Warteschlange", async () => {
    setup([]);
    expect(await screen.findByText("Alles geprüft")).toBeInTheDocument();
    expect(
      await screen.findByText(/72 Dokument\(e\) warten aufs Auslesen – Mac ist erreichbar/),
    ).toBeInTheDocument();
  });

  it("leerer Zustand ohne Warteschlange und ohne Rechner", async () => {
    server.use(
      statusHandler({
        ...healthyStatus,
        queue: { queued: 0, running: 0, failed: 0, succeeded: 0 },
      }),
    );
    setup([]);
    expect(await screen.findByText("Keine Dokumente in der Warteschlange.")).toBeInTheDocument();

    server.use(statusHandler({ ...healthyStatus, hosts: [] }));
  });

  it("meldet Ladefehler", async () => {
    server.use(
      http.get("*/api/suggestions", () => HttpResponse.json({ detail: "DB weg" }, { status: 500 })),
    );
    renderApp("/pruefen");
    expect(await screen.findByRole("alert")).toHaveTextContent("DB weg");
  });

  it("navigiert mit den Pfeil-Schaltflächen", async () => {
    setup();
    await screen.findByDisplayValue("Bürostuhl 1");
    fireEvent.click(screen.getByRole("button", { name: "Nächster Vorschlag" }));
    expect(await screen.findByDisplayValue("Bürostuhl 2")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Vorheriger Vorschlag" }));
    expect(await screen.findByDisplayValue("Bürostuhl 1")).toBeInTheDocument();
  });
});

describe("Hilfsfunktionen", () => {
  it("formatiert Daten und Namen", () => {
    expect(formatDate("2025-09-12")).toBe("12.09.2025");
    expect(formatDate(null)).toBe("–");
    expect(nameOf(new Map([[1, "A"]]), 1)).toBe("A");
    expect(nameOf(new Map(), 7)).toBe("#7");
    expect(nameOf(new Map(), null)).toBe("–");
  });
});
