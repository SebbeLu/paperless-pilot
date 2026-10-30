import {
  createRootRoute,
  createRoute,
  createRouter,
  type RouterHistory,
} from "@tanstack/react-router";
import { AppShell } from "@/components/app-shell";
import { OverviewPage } from "@/features/overview/overview-page";
import { PlaceholderPage } from "@/features/placeholder-page";
import { TaxonomyPage } from "@/features/rules/taxonomy-page";

const rootRoute = createRootRoute({ component: AppShell });

const placeholders = [
  {
    path: "/pruefen",
    title: "Prüfen",
    description: "Vorschläge der KI ansehen, korrigieren und übernehmen.",
    phase: 1,
  },
  {
    path: "/aufraeumen",
    title: "Aufräumen",
    description: "Doppelte Tags und Korrespondenten zusammenführen.",
    phase: 2,
  },
  {
    path: "/rechner",
    title: "Rechner & Modelle",
    description: "Wann welcher Rechner arbeiten darf und welches Modell am besten passt.",
    phase: 1,
  },
  {
    path: "/verlauf",
    title: "Verlauf",
    description: "Jede Änderung an Paperless, mit Rückgängig.",
    phase: 1,
  },
] as const;

const routeTree = rootRoute.addChildren([
  createRoute({ getParentRoute: () => rootRoute, path: "/", component: OverviewPage }),
  createRoute({ getParentRoute: () => rootRoute, path: "/regeln", component: TaxonomyPage }),
  ...placeholders.map(({ path, ...props }) =>
    createRoute({
      getParentRoute: () => rootRoute,
      path,
      component: () => <PlaceholderPage {...props} />,
    }),
  ),
]);

export function createAppRouter(history?: RouterHistory) {
  return createRouter({ routeTree, ...(history ? { history } : {}) });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}
