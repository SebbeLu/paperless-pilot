import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import type { Taxonomy, TaxonomyState } from "@/api/client";
import { renderApp } from "@/test/render";
import { server } from "@/test/server";
import { emptyTaxonomyState, linked } from "@/test/taxonomy-fixtures";
import { findDuplicates, normalizeTaxonomy } from "./taxonomy-page";

function serve(initial: TaxonomyState) {
  let state = initial;
  const saved: Taxonomy[] = [];
  let synced = 0;
  server.use(
    http.get("*/api/taxonomy", () => HttpResponse.json(state)),
    http.put("*/api/taxonomy", async ({ request }) => {
      const taxonomy = normalizeTaxonomy((await request.json()) as Taxonomy);
      saved.push(taxonomy);
      const names = [
        ...(taxonomy.document_types ?? []),
        ...(taxonomy.persons ?? []),
        ...(taxonomy.areas ?? []),
      ];
      state = {
        configured: true,
        taxonomy,
        sync: [
          ...state.sync.filter((s) => s.group === "status"),
          ...names.map((e) => ({
            group: "document_types" as const,
            name: e.name,
            status: "missing" as const,
            paperless_id: null,
            paperless_name: null,
          })),
        ],
      };
      return HttpResponse.json(state);
    }),
    http.post("*/api/taxonomy/sync", () => {
      synced += 1;
      state = linked(state);
      return HttpResponse.json(state);
    }),
  );
  return { saved, synced: () => synced };
}

describe("Regeln: Taxonomie", () => {
  it("führt neue Nutzer und legt fehlende Einträge in Paperless an", async () => {
    const backend = serve(emptyTaxonomyState);
    renderApp("/regeln");

    expect(await screen.findByText(/Noch keine Taxonomie gespeichert/)).toBeInTheDocument();
    expect(
      screen.getByText(/4 Einträge sind noch nicht mit Paperless verknüpft/),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "In Paperless anlegen" }));

    await waitFor(() => expect(backend.synced()).toBe(1));
    await waitFor(() =>
      expect(screen.queryByText(/noch nicht mit Paperless/)).not.toBeInTheDocument(),
    );
  });

  it("bearbeitet Einträge und speichert erst auf Knopfdruck", async () => {
    const backend = serve(linked(emptyTaxonomyState));
    renderApp("/regeln");

    await userEvent.click(
      await screen.findByRole("button", { name: "Dokumenttypen: Eintrag hinzufügen" }),
    );
    await userEvent.type(screen.getByRole("textbox", { name: "Dokumenttypen: Name" }), "Rechnung");
    await userEvent.type(
      screen.getByRole("textbox", { name: "Dokumenttypen: Beschreibung" }),
      "Rechnungen und Quittungen",
    );
    await userEvent.click(screen.getByRole("button", { name: "Personen: Eintrag hinzufügen" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Personen: Name" }), "Alex");
    await userEvent.type(screen.getByRole("textbox", { name: "Aliase" }), "A. Muster, Alexandra");

    expect(screen.getByText("Ungespeicherte Änderungen")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Speichern" }));

    await waitFor(() => expect(backend.saved).toHaveLength(1));
    const [saved] = backend.saved;
    expect(saved?.document_types).toEqual([
      { name: "Rechnung", description: "Rechnungen und Quittungen" },
    ]);
    expect(saved?.persons?.[0]?.aliases).toEqual(["A. Muster", "Alexandra"]);
    expect(await screen.findByText("fehlt in Paperless")).toBeInTheDocument();
  });

  it("verhindert doppelte Namen und erlaubt Verwerfen und Entfernen", async () => {
    serve(
      linked({
        ...emptyTaxonomyState,
        taxonomy: { ...emptyTaxonomyState.taxonomy, areas: [{ name: "Auto", description: "" }] },
      }),
    );
    renderApp("/regeln");

    const areas = (await screen.findByText("Lebensbereiche")).closest(
      "div.rounded-xl",
    ) as HTMLElement;
    await userEvent.click(
      within(areas).getByRole("button", { name: "Lebensbereiche: Eintrag hinzufügen" }),
    );
    const names = within(areas).getAllByRole("textbox", { name: "Lebensbereiche: Name" });
    await userEvent.type(names[1] as HTMLElement, "auto");

    expect(screen.getByText("Doppelte Namen: auto")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Speichern" })).toBeDisabled();

    await userEvent.click(within(areas).getByRole("button", { name: "auto entfernen" }));
    expect(screen.queryByText(/Doppelte Namen/)).not.toBeInTheDocument();
    await userEvent.click(within(areas).getByRole("button", { name: "Auto entfernen" }));
    expect(screen.getByText("Ungespeicherte Änderungen")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Verwerfen" }));
    expect(within(areas).getByDisplayValue("Auto")).toBeInTheDocument();
  });

  it("ändert erweiterte Einstellungen", async () => {
    const backend = serve(linked(emptyTaxonomyState));
    renderApp("/regeln");

    const pattern = await screen.findByDisplayValue("^o_");
    await userEvent.clear(pattern);
    await userEvent.type(pattern, "^Sammel");
    await userEvent.click(screen.getByRole("checkbox", { name: /Posteingangs-Tag/ }));
    const todo = screen.getByDisplayValue("ai:todo");
    await userEvent.clear(todo);
    await userEvent.type(todo, "ki:neu");
    await userEvent.click(screen.getByRole("button", { name: "Speichern" }));

    await waitFor(() => expect(backend.saved).toHaveLength(1));
    expect(backend.saved[0]).toMatchObject({
      correspondent_exclude_pattern: "^Sammel",
      remove_inbox_tag_on_accept: false,
      status: { todo: { name: "ki:neu" } },
    });
  });

  it("importiert eine Sicherung und meldet kaputte Dateien", async () => {
    const backend = serve(linked(emptyTaxonomyState));
    renderApp("/regeln");
    const input = await screen.findByLabelText("Sicherung importieren");

    fireEvent.change(input, { target: { files: [new File(["kein json"], "x.json")] } });
    expect(await screen.findByText("Die Datei ist kein gültiges JSON.")).toBeInTheDocument();

    const backup = { areas: [{ name: "Steuer" }] };
    fireEvent.change(input, { target: { files: [new File([JSON.stringify(backup)], "b.json")] } });
    await waitFor(() => expect(backend.saved).toHaveLength(1));
    expect(backend.saved[0]?.areas).toEqual([{ name: "Steuer", description: "" }]);
    expect(backend.saved[0]?.status?.todo.name).toBe("ai:todo");
    expect(await screen.findByDisplayValue("Steuer")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Exportieren" })).toHaveAttribute(
      "href",
      "/api/taxonomy/export",
    );
  });

  it("zeigt Fehler beim Speichern verständlich an", async () => {
    serve(linked(emptyTaxonomyState));
    server.use(
      http.put("*/api/taxonomy", () =>
        HttpResponse.json(
          { detail: [{ msg: "Value error, Ungültiger regulärer Ausdruck: x", loc: ["body"] }] },
          { status: 422 },
        ),
      ),
    );
    renderApp("/regeln");

    const pattern = await screen.findByDisplayValue("^o_");
    await userEvent.type(pattern, "(");
    await userEvent.click(screen.getByRole("button", { name: "Speichern" }));

    expect(
      await screen.findByText("Nicht gespeichert: Ungültiger regulärer Ausdruck: x"),
    ).toBeInTheDocument();
  });

  it("meldet, wenn die Taxonomie nicht geladen werden kann", async () => {
    server.use(
      http.get("*/api/taxonomy", () =>
        HttpResponse.json({ detail: "Paperless nicht erreichbar" }, { status: 503 }),
      ),
    );
    renderApp("/regeln");

    expect(await screen.findByRole("alert")).toHaveTextContent("Paperless nicht erreichbar");
  });
});

describe("findDuplicates", () => {
  it("vergleicht Tags gruppenübergreifend, Dokumenttypen getrennt", () => {
    const entry = (name: string) => ({ name, description: "" });
    const taxonomy = normalizeTaxonomy({
      document_types: [entry("Steuer")],
      persons: [{ ...entry("Alex"), aliases: [] }],
      areas: [entry("Steuer"), entry("ALEX"), entry(" ")],
    });
    expect(findDuplicates(taxonomy)).toEqual(["ALEX"]);
  });
});
