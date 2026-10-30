import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderApp } from "@/test/render";

describe("Navigation", () => {
  it("führt zu allen Bereichen und markiert den aktiven", async () => {
    const { router } = renderApp();
    const nav = await screen.findByRole("navigation", { name: "Hauptnavigation" });

    await userEvent.click(screen.getByRole("link", { name: "Prüfen" }));

    expect(await screen.findByRole("heading", { level: 1, name: "Prüfen" })).toBeInTheDocument();
    expect(screen.getByText("Kommt in Phase 1")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/pruefen");
    expect(screen.getByRole("link", { name: "Prüfen" })).toHaveAttribute("data-status", "active");
    expect(screen.getByRole("link", { name: "Übersicht" })).not.toHaveAttribute(
      "data-status",
      "active",
    );
    expect(nav.querySelectorAll("a")).toHaveLength(6);
  });

  it.each([
    ["/aufraeumen", "Aufräumen", 2],
    ["/verlauf", "Verlauf", 1],
  ])("öffnet %s direkt", async (path, title, phase) => {
    renderApp(path);

    expect(await screen.findByRole("heading", { level: 1, name: title })).toBeInTheDocument();
    expect(screen.getByText(`Kommt in Phase ${phase}`)).toBeInTheDocument();
  });
});
