import { Link } from "@tanstack/react-router";
import {
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  Keyboard,
  PartyPopper,
  RotateCcw,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, type MetadataValues, type Suggestion } from "@/api/client";
import {
  useAcceptSuggestion,
  useLookups,
  useReextractSuggestion,
  useRejectSuggestion,
  useSuggestion,
  useSuggestions,
  useSystemStatus,
  useTaxonomy,
} from "@/api/queries";
import { PageHeader } from "@/components/page-header";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { ReviewForm } from "./review-form";

export function ReviewPage() {
  const { data: suggestions, error, isPending } = useSuggestions();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [showHelp, setShowHelp] = useState(false);

  const list = suggestions ?? [];
  const index = Math.max(
    0,
    list.findIndex((s) => s.id === selectedId),
  );
  const current = list[index] ?? null;

  // Auswahl bleibt an derselben Position, wenn der aktuelle Vorschlag verschwindet.
  const lastIndex = useRef(0);
  useEffect(() => {
    if (!suggestions?.length) return;
    if (!suggestions.some((s) => s.id === selectedId)) {
      const next = suggestions[Math.min(lastIndex.current, suggestions.length - 1)];
      setSelectedId(next?.id ?? null);
    }
  }, [suggestions, selectedId]);
  useEffect(() => {
    lastIndex.current = index;
  }, [index]);

  const go = useCallback(
    (delta: number) => {
      const next = list[Math.min(Math.max(index + delta, 0), list.length - 1)];
      if (next) setSelectedId(next.id);
    },
    [list, index],
  );

  return (
    <>
      <PageHeader
        title="Prüfen"
        description={
          list.length
            ? `${list.length === 1 ? "1 Vorschlag" : `${list.length} Vorschläge`} offen · unsichere zuerst`
            : "Vorschläge der KI ansehen, korrigieren und übernehmen."
        }
        actions={
          <Button onClick={() => setShowHelp((v) => !v)} aria-expanded={showHelp}>
            <Keyboard className="size-4" aria-hidden="true" />
            Tastatur
          </Button>
        }
      />
      {showHelp && <KeyboardHelp />}
      {error && <Alert tone="danger">{error.message}</Alert>}
      {isPending && <p className="text-sm text-zinc-500">Lädt …</p>}
      {suggestions && list.length === 0 && <EmptyState />}
      {current && (
        <div className="grid gap-4 lg:grid-cols-[15rem_minmax(0,1fr)_24rem]">
          <SuggestionList items={list} selected={current.id} onSelect={setSelectedId} />
          <Preview documentId={current.document_id} />
          <Review
            key={current.id}
            suggestion={current}
            position={`${index + 1} von ${list.length}`}
            onPrevious={() => go(-1)}
            onNext={() => go(1)}
            onToggleHelp={() => setShowHelp((v) => !v)}
          />
        </div>
      )}
    </>
  );
}

function SuggestionList({
  items,
  selected,
  onSelect,
}: {
  items: Suggestion[];
  selected: number;
  onSelect: (id: number) => void;
}) {
  return (
    <nav aria-label="Offene Vorschläge" className="hidden max-h-[75vh] overflow-y-auto lg:block">
      <ul className="space-y-1">
        {items.map((item) => {
          const warnings = Object.values(item.checks).filter((c) => c.status === "warn").length;
          return (
            <li key={item.id}>
              <button
                type="button"
                onClick={() => onSelect(item.id)}
                aria-current={item.id === selected || undefined}
                className={cn(
                  "w-full rounded-lg px-3 py-2 text-left text-sm transition-colors",
                  item.id === selected
                    ? "bg-brand-50 text-brand-700 dark:bg-zinc-800 dark:text-brand-100"
                    : "hover:bg-zinc-100 dark:hover:bg-zinc-800",
                )}
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="truncate font-medium">
                    {item.proposed.title || item.current.title}
                  </span>
                  {warnings > 0 && (
                    <AlertTriangle
                      className="size-3.5 shrink-0 text-amber-500"
                      aria-label={`${warnings} Hinweise`}
                    />
                  )}
                </span>
                <span className="block truncate text-xs text-zinc-500 dark:text-zinc-400">
                  bisher: {item.current.title}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

function Preview({ documentId }: { documentId: number }) {
  return (
    <Card className="overflow-hidden">
      <iframe
        key={documentId}
        title={`Vorschau Dokument ${documentId}`}
        src={`/api/documents/${documentId}/preview`}
        className="h-[60vh] w-full bg-zinc-100 lg:h-[75vh] dark:bg-zinc-900"
      />
    </Card>
  );
}

function Review({
  suggestion,
  position,
  onPrevious,
  onNext,
  onToggleHelp,
}: {
  suggestion: Suggestion;
  position: string;
  onPrevious: () => void;
  onNext: () => void;
  onToggleHelp: () => void;
}) {
  const detail = useSuggestion(suggestion.id);
  const taxonomy = useTaxonomy();
  const lookups = useLookups();
  const accept = useAcceptSuggestion();
  const reject = useRejectSuggestion();
  const reextract = useReextractSuggestion();
  const [values, setValues] = useState<MetadataValues>(suggestion.proposed);
  const formRef = useRef<HTMLFormElement>(null);

  const conflict =
    accept.error instanceof ApiError && accept.error.status === 409 ? accept.error : null;
  const busy = accept.isPending || reject.isPending || reextract.isPending;
  const live = detail.data?.live ?? suggestion.current;

  const doAccept = useCallback(
    (force = false) => {
      if (!busy) accept.mutate({ id: suggestion.id, values, force });
    },
    [accept, busy, suggestion.id, values],
  );

  useReviewKeys({
    onAccept: () => doAccept(),
    onReject: () => !busy && reject.mutate(suggestion.id),
    onNext,
    onPrevious,
    onEdit: () => {
      const target =
        formRef.current?.querySelector<HTMLElement>(
          "[data-warn] input, [data-warn] select, [data-warn] button",
        ) ?? formRef.current?.querySelector<HTMLElement>("input, select");
      target?.focus();
    },
    onHelp: onToggleHelp,
  });

  const changedSince = detail.data?.changed_since ?? [];

  return (
    <Card className="flex flex-col p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">
            {detail.data?.original_file_name ?? `Dokument ${suggestion.document_id}`}
          </p>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            {position} · {suggestion.model} auf {suggestion.host} ·{" "}
            {Math.round(suggestion.duration_ms / 1000)} s
          </p>
        </div>
        <div className="flex">
          <Button onClick={onPrevious} aria-label="Vorheriger Vorschlag">
            <ChevronLeft className="size-4" aria-hidden="true" />
          </Button>
          <Button onClick={onNext} aria-label="Nächster Vorschlag">
            <ChevronRight className="size-4" aria-hidden="true" />
          </Button>
        </div>
      </div>

      {changedSince.length > 0 && !conflict && (
        <Alert tone="warning" className="mb-3">
          Seit dem Auslesen in Paperless geändert: {changedSince.join(", ")}.
        </Alert>
      )}

      <form
        ref={formRef}
        onSubmit={(e) => {
          e.preventDefault();
          doAccept();
        }}
        className="flex flex-1 flex-col gap-4"
      >
        {taxonomy.data && lookups.data ? (
          <ReviewForm
            values={values}
            live={live}
            checks={suggestion.checks}
            taxonomy={taxonomy.data.taxonomy}
            lookups={lookups.data}
            onChange={setValues}
          />
        ) : (
          <p className="text-sm text-zinc-500">Lädt Auswahllisten …</p>
        )}

        {conflict && (
          <Alert tone="warning" className="flex-col">
            <span>{conflict.message}.</span>
            <span className="flex flex-wrap gap-2">
              <Button variant="primary" onClick={() => doAccept(true)}>
                Trotzdem übernehmen
              </Button>
              <Button onClick={() => reextract.mutate(suggestion.id)}>Neu auslesen</Button>
            </span>
          </Alert>
        )}
        {[accept.error, reject.error, reextract.error].map(
          (err) =>
            err &&
            err !== conflict && (
              <Alert key={err.message} tone="danger">
                {err.message}
              </Alert>
            ),
        )}

        <div className="mt-auto flex flex-wrap gap-2 border-t border-zinc-100 pt-3 dark:border-zinc-800">
          <Button type="submit" variant="primary" size="md" disabled={busy} className="flex-1">
            Übernehmen <kbd className="ml-1 text-xs opacity-70">Enter</kbd>
          </Button>
          <Button size="md" onClick={() => reject.mutate(suggestion.id)} disabled={busy}>
            Verwerfen <kbd className="ml-1 text-xs opacity-70">R</kbd>
          </Button>
          <Button
            size="md"
            onClick={() => reextract.mutate(suggestion.id)}
            disabled={busy}
            aria-label="Neu auslesen"
          >
            <RotateCcw className="size-4" aria-hidden="true" />
          </Button>
        </div>
      </form>
    </Card>
  );
}

type KeyHandlers = {
  onAccept: () => void;
  onReject: () => void;
  onNext: () => void;
  onPrevious: () => void;
  onEdit: () => void;
  onHelp: () => void;
};

/** J/K blättern, Enter übernimmt, R verwirft, E springt ins erste unsichere Feld, ? Hilfe. */
export function useReviewKeys(handlers: KeyHandlers) {
  const ref = useRef(handlers);
  ref.current = handlers;
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      if (event.key === "Escape") {
        target?.blur();
        return;
      }
      if (target?.closest("input, select, textarea, [contenteditable]")) {
        return; // Enter im Formular übernimmt über das Absenden
      }
      const action = (
        {
          j: ref.current.onNext,
          k: ref.current.onPrevious,
          r: ref.current.onReject,
          e: ref.current.onEdit,
          "?": ref.current.onHelp,
          Enter: ref.current.onAccept,
        } as Record<string, (() => void) | undefined>
      )[event.key];
      if (action && !(event.key === "Enter" && target?.closest("button"))) {
        event.preventDefault();
        action();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

function KeyboardHelp() {
  const keys = [
    ["Enter", "Übernehmen (auch im Formular)"],
    ["J / K", "Nächster / vorheriger Vorschlag"],
    ["R", "Verwerfen"],
    ["E", "Ins erste unsichere Feld springen"],
    ["Esc", "Feld verlassen"],
    ["?", "Diese Hilfe"],
  ];
  return (
    <Card className="mb-4 p-4">
      <dl className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
        {keys.map(([key, text]) => (
          <div key={key} className="flex gap-3">
            <dt className="w-16 shrink-0 font-mono text-xs">{key}</dt>
            <dd>{text}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

function EmptyState() {
  const { data } = useSystemStatus();
  const waiting = data ? data.queue.queued + data.queue.running : 0;
  const message = useMemo(() => {
    if (!data) return "";
    if (waiting === 0) return "Keine Dokumente in der Warteschlange.";
    const ready = data.hosts.filter((h) => h.reachable).map((h) => h.name);
    return `${waiting} Dokument(e) warten aufs Auslesen${ready.length ? ` – ${ready.join(", ")} ist erreichbar` : " – gerade ist kein Rechner erreichbar"}.`;
  }, [data, waiting]);
  return (
    <Card className="flex flex-col items-center gap-3 px-6 py-16 text-center">
      <PartyPopper className="size-8 text-brand-600" aria-hidden="true" />
      <p className="font-medium">Alles geprüft</p>
      <p className="max-w-md text-sm text-zinc-500 dark:text-zinc-400">{message}</p>
      <Link
        to="/rechner"
        className="text-sm font-medium text-brand-700 hover:underline dark:text-brand-100"
      >
        Zu den Rechnern →
      </Link>
    </Card>
  );
}
