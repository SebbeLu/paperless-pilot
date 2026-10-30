import { screen } from "@testing-library/react";
import { renderApp } from "@/test/render";

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  listeners = new Map<string, () => void>();
  closed = false;
  constructor(readonly url: string) {
    FakeEventSource.instances.push(this);
  }
  addEventListener(topic: string, listener: () => void) {
    this.listeners.set(topic, listener);
  }
  close() {
    this.closed = true;
  }
}

describe("Live-Aktualisierung", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    FakeEventSource.instances = [];
  });

  it("abonniert Ereignisse und lädt betroffene Daten neu", async () => {
    vi.stubGlobal("EventSource", FakeEventSource);
    const { queryClient, unmount } = renderApp();
    await screen.findByText("709");
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    const [source] = FakeEventSource.instances;
    expect(source?.url).toBe("/api/events");
    for (const topic of ["jobs", "suggestions", "changes", "hosts", "taxonomy"]) {
      source?.listeners.get(topic)?.();
    }

    const keys = invalidate.mock.calls.map(([filters]) => filters?.queryKey?.[0]);
    expect(new Set(keys)).toEqual(
      new Set(["jobs", "system-status", "suggestions", "changes", "hosts", "taxonomy", "lookups"]),
    );
    unmount();
    expect(source?.closed).toBe(true);
  });
});
