import { AlertTriangle, Columns2, X } from "lucide-react";
import { useMemo } from "react";
import type { TranscriptionSummary } from "@/api/client";
import { AiIcon } from "@/components/ai-icon";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { type DiffKind, type DiffPart, suspiciousWords, wordDiff } from "@/lib/word-diff";

const score = (value: number) =>
  value.toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** Abschnitt „Text“ der Prüfkarte: vom Bild abgeschriebener Text, nur mit Haken übernommen. */
export function TextSection({
  summary,
  apply,
  onApplyChange,
  comparing,
  onToggleCompare,
}: {
  summary: TranscriptionSummary;
  apply: boolean;
  onApplyChange: (apply: boolean) => void;
  comparing: boolean;
  onToggleCompare: () => void;
}) {
  const details = [
    summary.pages === 1 ? "1 Seite" : `${summary.pages} Seiten`,
    summary.rotated_pages.length > 0 &&
      `aufgerichtet: ${summary.rotated_pages.length === 1 ? "Seite" : "Seiten"} ${summary.rotated_pages.join(", ")}`,
    `${summary.model} auf ${summary.host}`,
    `${Math.round(summary.duration_seconds)} s`,
  ].filter(Boolean);
  return (
    <section
      aria-labelledby="text-heading"
      className="space-y-2 rounded-lg border border-violet-200 bg-violet-50/50 p-3 dark:border-violet-900 dark:bg-violet-950/30"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id="text-heading" className="flex items-center gap-1.5 text-sm font-medium">
          <AiIcon />
          Text neu erkannt
        </h3>
        <span
          className="text-xs text-zinc-500 tabular-nums dark:text-zinc-400"
          title="Textqualität von 0 bis 1: vorher (Paperless-OCR) → nachher (vom Bild abgeschrieben)"
        >
          Qualität {score(summary.quality_before)} → {score(summary.quality_after)}
        </span>
      </div>
      <p className="text-xs text-zinc-500 dark:text-zinc-400">{details.join(" · ")}</p>
      <label className="flex items-start gap-2 text-sm">
        <input
          type="checkbox"
          className="mt-0.5 size-4 accent-brand-600"
          checked={apply}
          onChange={(e) => onApplyChange(e.target.checked)}
        />
        <span>
          Erkannten Text übernehmen
          <span className="block text-xs text-zinc-500 dark:text-zinc-400">
            ersetzt den Inhalt in Paperless; der alte Text bleibt im Verlauf
          </span>
        </span>
      </label>
      {summary.warnings.length > 0 && (
        <ul className="space-y-1 text-xs text-amber-800 dark:text-amber-300">
          {summary.warnings.map((w) => (
            <li key={w.code + w.message} className="flex gap-1.5">
              <AlertTriangle className="mt-px size-3.5 shrink-0" aria-hidden="true" />
              {w.message}
            </li>
          ))}
        </ul>
      )}
      {summary.skipped_pages > 0 && (
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          {summary.skipped_pages === 1
            ? "1 weitere Seite"
            : `${summary.skipped_pages} weitere Seiten`}{" "}
          nicht abgeschrieben.
        </p>
      )}
      <Button onClick={onToggleCompare} aria-pressed={comparing}>
        <Columns2 className="size-4" aria-hidden="true" />
        {comparing ? "Vorschau zeigen" : "Vergleichen"}
        <kbd className="ml-1 text-xs opacity-70">T</kbd>
      </Button>
    </section>
  );
}

/** Alt und neu nebeneinander; neue Wörter grün, weggefallene rot, verdächtige Stellen gelb. */
export function TextCompare({
  oldText,
  newText,
  summary,
  onClose,
}: {
  oldText: string | null | undefined;
  newText: string;
  summary: TranscriptionSummary;
  onClose: () => void;
}) {
  const diff = useMemo(() => {
    const old = oldText ?? "";
    return wordDiff(old, newText, suspiciousWords(old, flaggedIn(summary)));
  }, [oldText, newText, summary]);
  const warned = diff.new.some((p) => p.kind === "warn");
  return (
    <Card className="flex h-[60vh] flex-col overflow-hidden lg:h-[75vh]">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-zinc-100 px-4 py-2 text-xs dark:border-zinc-800">
        <span className="font-medium text-sm">Textvergleich</span>
        <Legend kind="removed" label="fehlt im neuen Text" />
        <Legend kind="added" label="neu erkannt" />
        {warned && <Legend kind="warn" label="prüfen: kommt im alten Text nicht vor" />}
        <Button className="ml-auto" onClick={onClose} aria-label="Vergleich schließen">
          <X className="size-4" aria-hidden="true" />
        </Button>
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-1 divide-zinc-100 sm:grid-cols-2 sm:divide-x dark:divide-zinc-800">
        <TextColumn title="Bisher in Paperless" parts={diff.old} empty="(kein Text)" />
        <TextColumn title="Vom Bild abgeschrieben" parts={diff.new} empty="(leer)" />
      </div>
    </Card>
  );
}

const MARK: Record<DiffKind, string> = {
  same: "",
  added: "rounded-sm bg-emerald-100 text-emerald-950 dark:bg-emerald-900/60 dark:text-emerald-50",
  removed: "rounded-sm bg-rose-100 text-rose-950 dark:bg-rose-900/50 dark:text-rose-50",
  warn: "rounded-sm bg-amber-200 text-amber-950 dark:bg-amber-600/70 dark:text-amber-50",
};

function TextColumn({ title, parts, empty }: { title: string; parts: DiffPart[]; empty: string }) {
  return (
    <div className="flex min-h-0 flex-col">
      <h4 className="px-4 pt-3 pb-1 text-xs font-medium text-zinc-500 dark:text-zinc-400">
        {title}
      </h4>
      <pre className="min-h-0 flex-1 overflow-auto px-4 pb-4 font-sans text-sm leading-relaxed whitespace-pre-wrap break-words">
        {parts.length === 0 ? (
          <span className="text-zinc-400">{empty}</span>
        ) : (
          parts.map((part, i) =>
            part.kind === "same" ? (
              part.text
            ) : (
              // biome-ignore lint/suspicious/noArrayIndexKey: Teile haben keine eigene Kennung
              <mark key={i} className={MARK[part.kind]} data-diff={part.kind}>
                {part.text}
              </mark>
            ),
          )
        )}
      </pre>
    </div>
  );
}

function Legend({ kind, label }: { kind: DiffKind; label: string }) {
  return (
    <span className="flex items-center gap-1.5 text-zinc-500 dark:text-zinc-400">
      <span className={cn("inline-block size-3", MARK[kind])} aria-hidden="true" />
      {label}
    </span>
  );
}

/** Stellen, die das Backend gemeldet hat: „IBAN-Prüfziffer falsch: DE89 …“, „Ungültiges Datum: …“ */
function flaggedIn(summary: TranscriptionSummary): string[] {
  return summary.warnings
    .filter((w) => ["iban", "date", "new_numbers"].includes(w.code))
    .flatMap((w) => (w.message.split(": ")[1] ?? "").split(/[\s,]+/))
    .filter((word) => word && word !== "…");
}
