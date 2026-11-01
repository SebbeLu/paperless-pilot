import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import type { Lesson } from "@/api/client";
import { renderApp } from "@/test/render";
import { server } from "@/test/server";
import { emptyTaxonomyState } from "@/test/taxonomy-fixtures";

const lesson: Lesson = {
  id: 3,
  document_id: 61,
  suggestion_id: 8,
  excerpt: "Muster Möbel GmbH · Hauptstraße 1 · Rechnung Nr. 4711",
  file_name: "rechnung.pdf",
  correct: {
    document_type: "Rechnung",
    correspondent: "Muster Möbel GmbH",
    created: "2025-09-12",
    persons: ["Alex", "Kim"],
    area: null,
    title: "Bürostuhl",
  },
  proposed: {
    document_type: "Rechnung",
    correspondent: "Muster Möbel GmbH",
    created: "2025-09-01",
    persons: ["Alex"],
    area: "Einkauf",
    title: "Bürostuhl",
  },
  corrected: ["created", "persons", "area"],
  created_at: "2026-10-31T12:00:00Z",
};

function serve(lessons: Lesson[], forgetStatus = 204) {
  let items = lessons;
  const forgotten: string[] = [];
  server.use(
    http.get("*/api/taxonomy", () => HttpResponse.json(emptyTaxonomyState)),
    http.get("*/api/lessons", () => HttpResponse.json(items)),
    http.delete("*/api/lessons/:id", ({ params }) => {
      if (forgetStatus !== 204) return HttpResponse.json(null, { status: forgetStatus });
      forgotten.push(String(params.id));
      items = items.filter((l) => String(l.id) !== params.id);
      return new HttpResponse(null, { status: 204 });
    }),
  );
  return forgotten;
}

describe("Regeln: gelernte Korrekturen", () => {
  it("zeigt Korrekturen mit dem früheren Vorschlag und vergisst sie auf Wunsch", async () => {
    const forgotten = serve([lesson]);
    renderApp("/regeln");

    expect(await screen.findByText("Dokument 61 · Muster Möbel GmbH")).toBeInTheDocument();
    expect(screen.getByText(/Datum: 12\.09\.2025/)).toBeInTheDocument();
    expect(screen.getByText("statt 01.09.2025")).toBeInTheDocument();
    expect(screen.getByText(/Personen: Alex, Kim/)).toBeInTheDocument();
    expect(screen.getByText(/Lebensbereich: –/)).toBeInTheDocument();
    expect(screen.getByText("statt Einkauf")).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: "Korrektur zu Dokument 61 vergessen" }),
    );

    await waitFor(() => expect(forgotten).toEqual(["3"]));
    expect(await screen.findByText("Noch keine Korrekturen.")).toBeInTheDocument();
  });

  it("meldet, wenn das Vergessen fehlschlägt", async () => {
    serve(
      [{ ...lesson, corrected: ["persons"], proposed: { ...lesson.proposed, persons: [] } }],
      500,
    );
    renderApp("/regeln");

    expect(await screen.findByText("statt keine")).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Korrektur zu Dokument 61 vergessen" }),
    );

    expect(
      await screen.findByText("Nicht vergessen: Backend antwortet mit HTTP 500"),
    ).toBeInTheDocument();
  });
});
