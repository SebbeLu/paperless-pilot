import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import type { HostRules, HostState } from "@/api/client";
import { renderApp } from "@/test/render";
import { server } from "@/test/server";
import { hostStatus } from "./hosts-page";

const base: HostState = {
  name: "Mac",
  url: "http://mac.local:11434",
  model: "gemma4:26b",
  online: true,
  version: "0.24.0",
  models: ["gemma4:26b"],
  has_model: true,
  problem: null,
  error: null,
  checked_at: "2026-10-30T12:00:00Z",
  rules: {
    paused: false,
    window: "20:00-07:00",
    idle_entity: "binary_sensor.mac_active",
    idle_state: "off",
    idle_minutes: 10,
    block_entity: null,
    block_state: "on",
  },
  decision: { allowed: false, reason: "Wartet: Rechner wird benutzt, Zeitfenster ab 20:00" },
  entity_states: {
    "binary_sensor.mac_active": { state: "on", last_changed: "2026-10-30T11:00:00Z" },
  },
  ha_available: true,
  busy_document_id: null,
  processed: 3,
  last_duration_ms: 23_400,
};

function serve(hosts: HostState[]) {
  const saved: HostRules[] = [];
  let refreshed = 0;
  server.use(
    http.get("*/api/hosts", () => HttpResponse.json(hosts)),
    http.post("*/api/hosts/refresh", () => {
      refreshed += 1;
      return HttpResponse.json(hosts);
    }),
    http.put("*/api/hosts/:name/rules", async ({ request }) => {
      const rules = (await request.json()) as HostRules;
      saved.push(rules);
      return HttpResponse.json({ ...hosts[0], rules });
    }),
  );
  return { saved, refreshed: () => refreshed };
}

describe("Rechner & Modelle", () => {
  it("erklärt, warum ein Rechner wartet, und zeigt Kennzahlen", async () => {
    serve([base]);
    renderApp("/rechner");

    expect(
      await screen.findByText("Wartet: Rechner wird benutzt, Zeitfenster ab 20:00"),
    ).toBeInTheDocument();
    expect(screen.getByText("Wartet")).toBeInTheDocument();
    expect(screen.getByText("3 Dokumente")).toBeInTheDocument();
    expect(screen.getByText("23 s")).toBeInTheDocument();
    expect(screen.getByText("on")).toBeInTheDocument();
  });

  it("pausiert und speichert Regeln", async () => {
    const backend = serve([base]);
    renderApp("/rechner");

    await userEvent.click(await screen.findByRole("button", { name: "Pausieren" }));
    await waitFor(() => expect(backend.saved).toHaveLength(1));
    expect(backend.saved[0]?.paused).toBe(true);

    const window = screen.getByLabelText("Zeitfenster");
    await userEvent.clear(window);
    await userEvent.type(window, "22:00-06:00");
    await userEvent.clear(screen.getByLabelText(/Leerlauf-Entität/));
    await userEvent.type(screen.getByLabelText(/Sperr-Entität/), "binary_sensor.pc_spiel");
    await userEvent.click(screen.getByRole("button", { name: "Regeln speichern" }));

    await waitFor(() => expect(backend.saved).toHaveLength(2));
    expect(backend.saved[1]).toMatchObject({
      window: "22:00-06:00",
      idle_entity: null,
      idle_minutes: 10,
      block_entity: "binary_sensor.pc_spiel",
    });
  });

  it("prüft auf Knopfdruck neu und zeigt Fehler beim Speichern", async () => {
    const backend = serve([base]);
    server.use(
      http.put("*/api/hosts/:name/rules", () =>
        HttpResponse.json(
          { detail: [{ msg: "Value error, Zeitfenster „x“ hat nicht das Format HH:MM-HH:MM" }] },
          { status: 422 },
        ),
      ),
    );
    renderApp("/rechner");

    await userEvent.click(await screen.findByRole("button", { name: "Jetzt prüfen" }));
    await waitFor(() => expect(backend.refreshed()).toBe(1));
    await userEvent.click(screen.getByRole("button", { name: "Regeln speichern" }));
    expect(await screen.findByText(/hat nicht das Format/)).toBeInTheDocument();
  });

  it("hilft bei fehlendem Modell, Offline-Rechner und ausgefallenem Home Assistant", async () => {
    serve([
      { ...base, name: "PC", has_model: false, models: [], ha_available: false, entity_states: {} },
      { ...base, name: "Laptop", online: false, error: "keine Verbindung" },
    ]);
    renderApp("/rechner");

    const pc = (await screen.findByRole("heading", { name: "PC" })).closest(
      "div.rounded-xl",
    ) as HTMLElement;
    expect(within(pc).getByText("Modell fehlt")).toBeInTheDocument();
    expect(within(pc).getByText("ollama pull gemma4:26b")).toBeInTheDocument();
    expect(within(pc).getByText(/es gilt nur das Zeitfenster/)).toBeInTheDocument();

    const laptop = screen
      .getByRole("heading", { name: "Laptop" })
      .closest("div.rounded-xl") as HTMLElement;
    expect(within(laptop).getByText("Nicht erreichbar: keine Verbindung.")).toBeInTheDocument();
  });

  it("zeigt Hinweis ohne Rechner und Ladefehler", async () => {
    serve([]);
    renderApp("/rechner");
    expect(await screen.findByText(/Noch kein Ollama-Rechner eingetragen/)).toBeInTheDocument();
  });

  it("meldet Fehler beim Laden", async () => {
    server.use(
      http.get("*/api/hosts", () => HttpResponse.json({ detail: "kaputt" }, { status: 500 })),
    );
    renderApp("/rechner");
    expect(await screen.findByRole("alert")).toHaveTextContent("kaputt");
  });
});

describe("hostStatus", () => {
  it.each([
    [{ online: false }, "Offline"],
    [{ busy_document_id: 4 }, "Arbeitet"],
    [{ has_model: false }, "Modell fehlt"],
    [{ rules: { ...base.rules, paused: true } }, "Pausiert"],
    [{ decision: { allowed: true, reason: "ok" } }, "Bereit"],
    [{}, "Wartet"],
  ])("%o → %s", (patch, label) => {
    expect(hostStatus({ ...base, ...patch } as HostState).label).toBe(label);
  });
});
