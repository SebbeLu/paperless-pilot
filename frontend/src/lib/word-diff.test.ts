import { describe, expect, it } from "vitest";
import { suspiciousWords, wordDiff } from "./word-diff";

describe("wordDiff", () => {
  it("markiert neue und weggefallene Wörter und behält Zeilenumbrüche", () => {
    const diff = wordDiff("Rechnung vom Mai\nBetrag 12,00", "Rechnung vom Juni\nBetrag 12,00");

    expect(diff.old).toEqual([
      { text: "Rechnung vom ", kind: "same" },
      { text: "Mai", kind: "removed" },
      { text: "\nBetrag 12,00", kind: "same" },
    ]);
    expect(diff.new).toEqual([
      { text: "Rechnung vom ", kind: "same" },
      { text: "Juni", kind: "added" },
      { text: "\nBetrag 12,00", kind: "same" },
    ]);
  });

  it("ignoriert Groß-/Kleinschreibung und Satzzeichen beim Vergleich", () => {
    const diff = wordDiff("RECHNUNG, Nr.", "Rechnung Nr");

    expect(diff.new).toEqual([{ text: "Rechnung Nr", kind: "same" }]);
  });

  it("fasst zusammenhängende Änderungen zusammen", () => {
    const diff = wordDiff("‚ _‚„ ﬁfa", "Sehr geehrte Damen");

    expect(diff.old).toEqual([{ text: "‚ _‚„ ﬁfa", kind: "removed" }]);
    expect(diff.new).toEqual([{ text: "Sehr geehrte Damen", kind: "added" }]);
  });

  it("vergleicht sehr lange Texte nur noch nach Vorkommen", () => {
    const old = Array.from({ length: 2500 }, (_, i) => `a${i}`).join(" ");
    const neu = Array.from({ length: 2500 }, (_, i) => `a${2499 - i}`).join(" ");

    const diff = wordDiff(old, neu);

    expect(diff.new.every((p) => p.kind === "same")).toBe(true);
  });

  it("markiert verdächtige Wörter im neuen Text gelb", () => {
    const diff = wordDiff("Summe 10", "Summe 1234", (w) => w === "1234");

    expect(diff.new.at(-1)).toEqual({ text: "1234", kind: "warn" });
  });
});

describe("suspiciousWords", () => {
  const old = "Kundennummer 123456 vom 01.02.2024, Rechnung 98765";

  it("meldet Zahlen, die im alten Text fehlen", () => {
    const check = suspiciousWords(old, []);

    expect(check("123456")).toBe(false);
    expect(check("01.02.2024")).toBe(false);
    expect(check("654321")).toBe(true);
    expect(check("12")).toBe(false);
    expect(check("Rechnung")).toBe(false);
  });

  it("vergleicht Zahlen nur, wenn der alte Text genug Ziffern hat", () => {
    expect(suspiciousWords("‚ _‚„", [])("654321")).toBe(false);
  });

  it("meldet Stellen aus den Warnungen", () => {
    expect(suspiciousWords("", ["DE89"])("DE89")).toBe(true);
  });
});
