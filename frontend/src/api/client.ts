import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

type Schemas = components["schemas"];
export type SystemStatus = Schemas["SystemStatus"];
export type PaperlessStatus = Schemas["PaperlessStatus"];
export type HostStatus = Schemas["HostStatus"];
export type Taxonomy = Schemas["Taxonomy"];
export type TaxonomyEntry = Schemas["TaxonomyEntry"];
export type PersonEntry = Schemas["PersonEntry"];
export type TaxonomyState = Schemas["TaxonomyState"];
export type SyncItem = Schemas["SyncItem"];
export type Lookups = Schemas["Lookups"];

export const api = createClient<paths>({
  baseUrl: globalThis.location?.origin ?? "",
  // fetch erst beim Aufruf auflösen, damit Test-Interceptoren (MSW) greifen.
  fetch: (request) => globalThis.fetch(request),
});

/** Fehler der API mit verständlicher Meldung (aus FastAPI-Validierung oder Domänenfehler). */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly body: unknown,
  ) {
    super(message);
  }
}

type ValidationItem = { msg?: string; loc?: (string | number)[] };

function messageOf(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return (detail as ValidationItem[])
        .map((d) => (d.msg ?? "").replace(/^Value error, /, ""))
        .filter(Boolean)
        .join(" · ");
    }
  }
  return `Backend antwortet mit HTTP ${status}`;
}

/** Wandelt das Ergebnis von openapi-fetch in Daten oder einen ApiError. */
export async function unwrap<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await call;
  if (!response.ok || data === undefined) {
    throw new ApiError(messageOf(error, response.status), response.status, error);
  }
  return data;
}
