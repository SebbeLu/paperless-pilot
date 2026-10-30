import { Link, Outlet } from "@tanstack/react-router";
import {
  Cpu,
  History,
  Inbox,
  LayoutDashboard,
  ListChecks,
  type LucideIcon,
  Sparkles,
} from "lucide-react";

export type NavItem = { to: string; label: string; icon: LucideIcon; hint: string };

export const NAV_ITEMS: NavItem[] = [
  {
    to: "/",
    label: "Übersicht",
    icon: LayoutDashboard,
    hint: "Rückstand, Fortschritt und Rechner",
  },
  { to: "/pruefen", label: "Prüfen", icon: Inbox, hint: "Vorschläge ansehen und übernehmen" },
  {
    to: "/aufraeumen",
    label: "Aufräumen",
    icon: Sparkles,
    hint: "Tags und Korrespondenten bereinigen",
  },
  { to: "/regeln", label: "Regeln", icon: ListChecks, hint: "Dokumenttypen, Felder und Titel" },
  { to: "/rechner", label: "Rechner & Modelle", icon: Cpu, hint: "Verfügbarkeit und Benchmark" },
  { to: "/verlauf", label: "Verlauf", icon: History, hint: "Alle Änderungen mit Rückgängig" },
];

export function AppShell() {
  return (
    <div className="flex min-h-dvh flex-col md:flex-row">
      <aside className="shrink-0 border-b border-zinc-200 bg-white px-3 py-3 md:w-60 md:border-r md:border-b-0 md:py-5 dark:border-zinc-800 dark:bg-zinc-900">
        <div className="mb-3 flex items-center gap-2 px-2 md:mb-6">
          <img src="/favicon.svg" alt="" className="size-7" />
          <span className="text-sm font-semibold tracking-tight">paperless-pilot</span>
        </div>
        <nav aria-label="Hauptnavigation">
          <ul className="-mx-1 flex gap-1 overflow-x-auto px-1 md:mx-0 md:block md:space-y-0.5 md:px-0">
            {NAV_ITEMS.map(({ to, label, icon: Icon, hint }) => (
              <li key={to}>
                <Link
                  to={to}
                  title={hint}
                  activeOptions={{ exact: to === "/" }}
                  className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm whitespace-nowrap md:gap-3 text-zinc-600 transition-colors hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100 data-[status=active]:bg-brand-50 data-[status=active]:font-medium data-[status=active]:text-brand-700 dark:data-[status=active]:bg-zinc-800 dark:data-[status=active]:text-brand-100"
                >
                  <Icon className="size-4" aria-hidden="true" />
                  {label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      </aside>
      <main className="min-w-0 flex-1 px-4 py-6 md:px-10 md:py-8">
        <div className="mx-auto max-w-6xl">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
