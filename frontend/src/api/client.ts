import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export type SystemStatus = components["schemas"]["SystemStatus"];
export type PaperlessStatus = components["schemas"]["PaperlessStatus"];
export type HostStatus = components["schemas"]["HostStatus"];

export const api = createClient<paths>({
  baseUrl: globalThis.location?.origin ?? "",
  // fetch erst beim Aufruf auflösen, damit Test-Interceptoren (MSW) greifen.
  fetch: (request) => globalThis.fetch(request),
});
