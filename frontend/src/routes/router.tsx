import {
  createRootRoute,
  createRoute,
  createRouter,
  type RouterHistory,
} from "@tanstack/react-router";
import { AppShell } from "@/components/app-shell";
import { HistoryPage } from "@/features/history/history-page";
import { HostsPage } from "@/features/hosts/hosts-page";
import { OverviewPage } from "@/features/overview/overview-page";
import { PlaceholderPage } from "@/features/placeholder-page";
import { ReviewPage } from "@/features/review/review-page";
import { TaxonomyPage } from "@/features/rules/taxonomy-page";

const rootRoute = createRootRoute({ component: AppShell });

const placeholders = [
  {
    path: "/aufraeumen",
    title: "Aufräumen",
    description: "Doppelte Tags und Korrespondenten zusammenführen.",
    phase: 2,
  },
] as const;

const routeTree = rootRoute.addChildren([
  createRoute({ getParentRoute: () => rootRoute, path: "/", component: OverviewPage }),
  createRoute({ getParentRoute: () => rootRoute, path: "/regeln", component: TaxonomyPage }),
  createRoute({ getParentRoute: () => rootRoute, path: "/rechner", component: HostsPage }),
  createRoute({ getParentRoute: () => rootRoute, path: "/pruefen", component: ReviewPage }),
  createRoute({ getParentRoute: () => rootRoute, path: "/verlauf", component: HistoryPage }),
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
