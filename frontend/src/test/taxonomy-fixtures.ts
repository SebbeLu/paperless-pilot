import type { TaxonomyState } from "@/api/client";

export const emptyTaxonomyState: TaxonomyState = {
  configured: false,
  taxonomy: {
    document_types: [],
    persons: [],
    areas: [],
    status: {
      todo: { name: "ai:todo", description: "", paperless_id: null },
      review: { name: "ai:prüfen", description: "", paperless_id: null },
      done: { name: "ai:fertig", description: "", paperless_id: null },
      error: { name: "ai:fehler", description: "", paperless_id: null },
    },
    correspondent_exclude_pattern: "^o_",
    remove_inbox_tag_on_accept: true,
  },
  sync: [
    {
      group: "status",
      name: "ai:todo",
      status: "missing",
      paperless_id: null,
      paperless_name: null,
    },
    {
      group: "status",
      name: "ai:prüfen",
      status: "missing",
      paperless_id: null,
      paperless_name: null,
    },
    {
      group: "status",
      name: "ai:fertig",
      status: "missing",
      paperless_id: null,
      paperless_name: null,
    },
    {
      group: "status",
      name: "ai:fehler",
      status: "missing",
      paperless_id: null,
      paperless_name: null,
    },
  ],
};

export function linked(state: TaxonomyState): TaxonomyState {
  return {
    ...state,
    configured: true,
    sync: state.sync.map((item, i) => ({ ...item, status: "linked", paperless_id: i + 1 })),
  };
}
