import { cn, formatBytes } from "./utils";

describe("cn", () => {
  it("führt Tailwind-Klassen konfliktfrei zusammen", () => {
    expect(cn("px-2", false, "px-4")).toBe("px-4");
  });
});

describe("formatBytes", () => {
  it.each([
    [512_000_000, "512 MB"],
    [17_987_581_215, "18 GB"],
    [9_639_236_355, "9,6 GB"],
  ])("%d → %s", (bytes, text) => {
    expect(formatBytes(bytes)).toBe(text);
  });
});
