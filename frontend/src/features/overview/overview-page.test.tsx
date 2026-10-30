import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { renderApp } from "@/test/render";
import { healthyStatus, server, statusHandler } from "@/test/server";

describe("Übersicht", () => {
  it("zeigt Kennzahlen aus Paperless", async () => {
    renderApp();

    expect(await screen.findByText("709")).toBeInTheDocument();
    expect(screen.getByText("95")).toBeInTheDocument();
    expect(screen.getByText("1 von 2")).toBeInTheDocument();
  });

  it("zeigt verbundene und ausgefallene Rechner verständlich an", async () => {
    renderApp();

    const mac = (await screen.findByRole("heading", { name: "Mac" })).closest("div.rounded-xl");
    expect(mac).not.toBeNull();
    expect(within(mac as HTMLElement).getByText("Bereit")).toBeInTheDocument();
    expect(
      within(mac as HTMLElement).getByRole("list", { name: "Modelle auf Mac" }),
    ).toHaveTextContent("gemma4:26b");

    const pc = screen.getByRole("heading", { name: "Gaming-PC" }).closest("div.rounded-xl");
    expect(within(pc as HTMLElement).getByText("Offline")).toBeInTheDocument();
    expect(within(pc as HTMLElement).getByText(/OLLAMA_HOST=0.0.0.0/)).toBeInTheDocument();
    expect(within(pc as HTMLElement).getByText(/Zeitüberschreitung/)).toBeInTheDocument();
  });

  it("erklärt einen abgelehnten API-Token", async () => {
    server.use(
      statusHandler({
        paperless: { reachable: false, problem: "auth", error: "HTTP 401" },
        hosts: [],
      }),
    );
    renderApp();

    expect(await screen.findByText("Nicht erreichbar")).toBeInTheDocument();
    expect(screen.getByText(/Token in der Konfiguration prüfen/)).toBeInTheDocument();
    expect(screen.getByText("HTTP 401")).toBeInTheDocument();
    expect(screen.getByText(/Noch kein Ollama-Rechner eingetragen/)).toBeInTheDocument();
    expect(screen.getAllByText("–")).toHaveLength(3);
  });

  it("unterscheidet Netzwerkprobleme von Zugangsproblemen", async () => {
    server.use(
      statusHandler({
        paperless: { reachable: false, problem: "unreachable", error: "Verbindung abgelehnt" },
        hosts: [
          { name: "Mac", url: "http://mac:11434", reachable: false, models: [], problem: "auth" },
        ],
      }),
    );
    renderApp();

    expect(await screen.findByText(/Läuft der Container/)).toBeInTheDocument();
    expect(screen.queryByText(/Token/)).not.toBeInTheDocument();
    expect(screen.getByText("Ollama verweigert den Zugriff.")).toBeInTheDocument();
  });

  it("zeigt einen Rechner ohne Modelle", async () => {
    const mac = {
      ...healthyStatus.hosts[0],
      name: "Mac",
      url: "http://mac:11434",
      reachable: true,
    };
    server.use(statusHandler({ ...healthyStatus, hosts: [{ ...mac, models: [] }] }));
    renderApp();

    expect(await screen.findByText("Keine Modelle installiert.")).toBeInTheDocument();
  });

  it("meldet, wenn der Dienst selbst nicht antwortet", async () => {
    server.use(http.get("*/api/system/status", () => new HttpResponse(null, { status: 502 })));
    renderApp();

    expect(await screen.findByRole("alert")).toHaveTextContent("HTTP 502");
  });

  it("lädt den Status auf Knopfdruck neu", async () => {
    let calls = 0;
    server.use(
      http.get("*/api/system/status", () => {
        calls += 1;
        return HttpResponse.json(healthyStatus);
      }),
    );
    renderApp();
    await screen.findByText("709");

    await userEvent.click(screen.getByRole("button", { name: "Status neu laden" }));

    await vi.waitFor(() => expect(calls).toBe(2));
    expect(screen.getByText(/aktualisiert sich automatisch/)).toBeInTheDocument();
  });
});
