import { HttpResponse, http } from "msw";
import type {
  Change,
  Lookups,
  MetadataValues,
  Suggestion,
  SuggestionDetail,
  TaxonomyState,
} from "@/api/client";
import { emptyTaxonomyState } from "./taxonomy-fixtures";

const entry = (name: string, paperless_id: number, description = "") => ({
  name,
  description,
  paperless_id,
});

export const reviewTaxonomy: TaxonomyState = {
  configured: true,
  sync: [],
  taxonomy: {
    ...emptyTaxonomyState.taxonomy,
    document_types: [entry("Rechnung", 10), entry("Bescheid", 11)],
    persons: [
      { ...entry("Alex", 20), aliases: ["Alexandra Muster"] },
      { ...entry("Kim", 21), aliases: [] },
    ],
    areas: [entry("Einkauf", 30), entry("Steuer", 31)],
  },
};

export const lookups: Lookups = {
  correspondents: [
    { id: 90, name: "o_Online-Shops", excluded: true },
    { id: 91, name: "Muster Möbel", excluded: false },
    { id: 92, name: "Finanzamt Musterstadt", excluded: false },
  ],
  document_types: [
    { id: 10, name: "Rechnung" },
    { id: 11, name: "Bescheid" },
    { id: 50, name: "Bescheinigung" },
  ],
  tags: [
    { id: 20, name: "Alex" },
    { id: 21, name: "Kim" },
    { id: 30, name: "Einkauf" },
    { id: 31, name: "Steuer" },
  ],
};

const current: MetadataValues = {
  title: "SwiftScan 2026-10-07",
  document_type_id: 50,
  correspondent_id: 90,
  new_correspondent: null,
  created: "2026-10-07",
  person_tag_ids: [],
  area_tag_id: null,
};

export function suggestion(id: number, overrides: Partial<Suggestion> = {}): Suggestion {
  return {
    id,
    document_id: 700 + id,
    job_id: id,
    status: "open",
    model: "gemma4:26b",
    host: "Mac",
    duration_ms: 23_000,
    document_modified: "2026-10-30T12:00:00Z",
    created_at: "2026-10-30T12:00:00Z",
    decided_at: null,
    note: null,
    current,
    proposed: {
      title: `Bürostuhl ${id}`,
      document_type_id: 10,
      correspondent_id: 91,
      new_correspondent: null,
      created: "2025-09-12",
      person_tag_ids: [20],
      area_tag_id: 30,
    },
    checks: {
      document_type: { status: "ok", message: "vom Modell gewählt", evidence: null },
      correspondent: { status: "ok", message: "vorhanden", evidence: "Muster Möbel GmbH" },
      created: { status: "ok", message: "belegt", evidence: "den 12.09.2025" },
      persons: { status: "warn", message: "im Text nicht gefunden: Alex", evidence: null },
      area: { status: "ok", message: "vom Modell gewählt", evidence: null },
      title: { status: "ok", message: "", evidence: null },
    },
    lesson_ids: [],
    ...overrides,
  };
}

export function detail(s: Suggestion, overrides: Partial<SuggestionDetail> = {}): SuggestionDetail {
  return {
    suggestion: s,
    live: s.current,
    original_file_name: `scan-${s.id}.pdf`,
    changed_since: [],
    ...overrides,
  };
}

export type ReviewBackend = {
  accepted: { id: number; body: { values: MetadataValues; force: boolean } }[];
  acceptedMany: number[][];
  rejected: number[];
  reextracted: number[];
  reverted: number[];
};

export function change(id: number, overrides: Partial<Change> = {}): Change {
  const state = {
    title: "SwiftScan 2026-10-07",
    document_type_id: 50,
    correspondent_id: 90,
    created: "2026-10-07",
    tag_ids: [1, 41],
  };
  return {
    id,
    document_id: 701,
    suggestion_id: 1,
    kind: "apply",
    actor: "user",
    before: state,
    after: {
      ...state,
      title: "Bürostuhl 1",
      document_type_id: 10,
      correspondent_id: 91,
      created: "2025-09-12",
      tag_ids: [20, 30, 42],
    },
    created_at: "2026-10-30T12:30:00Z",
    reverted_by: null,
    ...overrides,
  };
}

/** Kleines Backend: Liste schrumpft nach Entscheidungen. */
export function reviewHandlers(
  initial: Suggestion[],
  options: { conflictOnce?: boolean; failIds?: number[] } = {},
) {
  let open = [...initial];
  let conflict = options.conflictOnce ?? false;
  const backend: ReviewBackend = {
    accepted: [],
    acceptedMany: [],
    rejected: [],
    reextracted: [],
    reverted: [],
  };
  const remove = (id: number) => {
    open = open.filter((s) => s.id !== id);
  };
  const handlers = [
    http.get("*/api/taxonomy", () => HttpResponse.json(reviewTaxonomy)),
    http.get("*/api/paperless/lookups", () => HttpResponse.json(lookups)),
    http.get("*/api/suggestions", () => HttpResponse.json(open)),
    http.get("*/api/suggestions/:id", ({ params }) => {
      const found = initial.find((s) => s.id === Number(params.id));
      return found
        ? HttpResponse.json(detail(found))
        : HttpResponse.json({ detail: "fehlt" }, { status: 404 });
    }),
    http.post("*/api/suggestions/accept", async ({ request }) => {
      const { ids } = (await request.json()) as { ids: number[] };
      backend.acceptedMany.push(ids);
      const fail = new Set(options.failIds ?? []);
      for (const id of ids) if (!fail.has(id)) remove(id);
      return HttpResponse.json({
        accepted: ids
          .filter((id) => !fail.has(id))
          .map((id) => change(100 + id, { suggestion_id: id })),
        failed: ids
          .filter((id) => fail.has(id))
          .map((id) => ({ suggestion_id: id, message: "In Paperless geändert (Titel)" })),
      });
    }),
    http.post("*/api/suggestions/:id/accept", async ({ params, request }) => {
      const body = (await request.json()) as ReviewBackend["accepted"][number]["body"];
      if (conflict && !body.force) {
        conflict = false;
        return HttpResponse.json(
          {
            detail: "Das Dokument wurde seit dem Auslesen in Paperless geändert (Titel)",
            conflict: ["Titel"],
          },
          { status: 409 },
        );
      }
      backend.accepted.push({ id: Number(params.id), body });
      remove(Number(params.id));
      return HttpResponse.json(
        change(100 + Number(params.id), { suggestion_id: Number(params.id) }),
      );
    }),
    http.post("*/api/suggestions/:id/reject", ({ params }) => {
      backend.rejected.push(Number(params.id));
      remove(Number(params.id));
      return HttpResponse.json({});
    }),
    http.post("*/api/changes/:id/revert", ({ params }) => {
      const id = Number(params.id);
      backend.reverted.push(id);
      const restored = initial.find((s) => s.id === id - 100);
      if (restored) open = [restored, ...open];
      return HttpResponse.json(change(200, { kind: "revert" }));
    }),
    http.post("*/api/suggestions/:id/reextract", ({ params }) => {
      backend.reextracted.push(Number(params.id));
      remove(Number(params.id));
      return HttpResponse.json({});
    }),
  ];
  return { handlers, backend };
}
