import { Link } from "@tanstack/react-router";
import { ArrowRight, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  type Change,
  type DocumentFailure,
  type DocumentState,
  type Lookups,
} from "@/api/client";
import {
  useChanges,
  useLookups,
  useReextractDocuments,
  useRevertChange,
  useTranscribeDocuments,
  useVisionAvailable,
} from "@/api/queries";
import { AiIcon } from "@/components/ai-icon";
import { PageHeader } from "@/components/page-header";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { formatDate, nameMaps, nameOf } from "@/features/review/review-form";

const dateTime = new Intl.DateTimeFormat("de-DE", { dateStyle: "short", timeStyle: "short" });

export function HistoryPage() {
  const { data, error, isPending, fetchNextPage, hasNextPage, isFetchingNextPage } = useChanges();
  const lookups = useLookups();
  const changes = data?.pages.flat() ?? [];
  // Markiert werden Dokumente – mehrere Einträge desselben Dokuments teilen sich das Kästchen
  const [marked, setMarked] = useState<ReadonlySet<number>>(new Set());
  const [result, setResult] = useState<{
    enqueued: number;
    failed: DocumentFailure[];
    text: boolean;
  } | null>(null);
  const reextract = useReextractDocuments();
  const transcribe = useTranscribeDocuments();
  const busy = reextract.isPending || transcribe.isPending;
  const documentIds = [...new Set(changes.map((c) => c.document_id))];
  const toggle = useCallback((id: number) => {
    setMarked((prev) => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  }, []);
  const requeueMarked = (text: boolean) => {
    if (!marked.size || busy) return;
    (text ? transcribe : reextract).mutate([...marked], {
      onSuccess: (r) => {
        setResult({ enqueued: r.enqueued.length, failed: r.failed, text });
        setMarked(new Set(r.failed.map((f) => f.document_id)));
      },
    });
  };

  return (
    <>
      <PageHeader
        title="Verlauf"
        description="Jede Änderung, die paperless-pilot in Paperless geschrieben hat."
      />
      {result && result.enqueued > 0 && (
        <Alert className="mb-4 flex-wrap justify-between">
          <span>
            {result.enqueued === 1 ? "1 Dokument wird" : `${result.enqueued} Dokumente werden`} mit
            Vorrang {result.text ? "neu vom Bild abgeschrieben und ausgelesen" : "neu ausgelesen"}.
            Die neuen Vorschläge erscheinen unter Prüfen.
          </span>
          <Link
            to="/pruefen"
            className="text-sm font-medium text-brand-700 hover:underline dark:text-brand-100"
          >
            Zu Prüfen →
          </Link>
        </Alert>
      )}
      {result && result.failed.length > 0 && (
        <Alert tone="warning" className="mb-4 flex-col">
          <span>Nicht eingereiht, bleibt markiert:</span>
          <ul className="list-disc pl-5">
            {result.failed.map((f) => (
              <li key={f.document_id}>
                Dokument {f.document_id}: {f.message}
              </li>
            ))}
          </ul>
        </Alert>
      )}
      {[reextract.error, transcribe.error].map(
        (err) =>
          err && (
            <Alert key={err.message} tone="danger" className="mb-4">
              {err.message}
            </Alert>
          ),
      )}
      {changes.length > 0 && (
        <SelectionBar
          total={documentIds.length}
          marked={marked.size}
          busy={busy}
          onMarkAll={(all) => setMarked(new Set(all ? documentIds : []))}
          onReextract={() => requeueMarked(false)}
          onTranscribe={() => requeueMarked(true)}
        />
      )}
      {error && <Alert tone="danger">{error.message}</Alert>}
      {isPending && <p className="text-sm text-zinc-500">Lädt …</p>}
      {data && changes.length === 0 && (
        <Card className="px-6 py-12 text-center text-sm text-zinc-500 dark:text-zinc-400">
          Noch keine Änderungen. Übernommene Vorschläge erscheinen hier – mit Rückgängig.
        </Card>
      )}
      <ol className="space-y-3">
        {changes.map((change) => (
          <li key={change.id}>
            <ChangeCard
              change={change}
              lookups={lookups.data}
              marked={marked.has(change.document_id)}
              onToggle={toggle}
            />
          </li>
        ))}
      </ol>
      {hasNextPage && (
        <div className="mt-4 flex justify-center">
          <Button onClick={() => void fetchNextPage()} disabled={isFetchingNextPage}>
            Ältere laden
          </Button>
        </div>
      )}
    </>
  );
}

function SelectionBar({
  total,
  marked,
  busy,
  onMarkAll,
  onReextract,
  onTranscribe,
}: {
  total: number;
  marked: number;
  busy: boolean;
  onMarkAll: (all: boolean) => void;
  onReextract: () => void;
  onTranscribe: () => void;
}) {
  const vision = useVisionAvailable();
  const all = useRef<HTMLInputElement>(null);
  const some = marked > 0 && marked < total;
  useEffect(() => {
    if (all.current) all.current.indeterminate = some;
  }, [some]);
  return (
    <Card className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2">
      <label className="flex items-center gap-2 text-sm font-medium">
        <input
          ref={all}
          type="checkbox"
          className="size-4 accent-brand-600"
          checked={marked > 0 && marked === total}
          onChange={(e) => onMarkAll(e.target.checked)}
        />
        Alle markieren
      </label>
      <span className="text-sm text-zinc-500 dark:text-zinc-400">
        {marked
          ? `${marked === 1 ? "1 Dokument" : `${marked} Dokumente`} markiert`
          : "Dokumente markieren, um sie noch einmal auslesen zu lassen"}
      </span>
      <Button
        className="ml-auto"
        onClick={onTranscribe}
        disabled={busy || marked === 0 || !vision}
        title={
          vision
            ? "KI-Funktion: Text mit Vorrang neu vom Bild abschreiben, danach neu auslesen; neue Vorschläge kommen unter Prüfen"
            : "Kein Rechner mit Vision-Modell erreichbar"
        }
      >
        <AiIcon />
        {marked === 0 ? "Markierte Text neu erkennen" : `${marked} Text neu erkennen`}
      </Button>
      <Button
        onClick={onReextract}
        disabled={busy || marked === 0}
        title="KI-Funktion: Dokumente mit Vorrang noch einmal auslesen; neue Vorschläge kommen unter Prüfen"
      >
        <AiIcon />
        {marked === 0 ? "Markierte neu auslesen" : `${marked} neu auslesen`}
      </Button>
    </Card>
  );
}

function ChangeCard({
  change,
  lookups,
  marked,
  onToggle,
}: {
  change: Change;
  lookups: Lookups | undefined;
  marked: boolean;
  onToggle: (documentId: number) => void;
}) {
  const revert = useRevertChange();
  const [confirmForce, setConfirmForce] = useState(false);
  const conflict =
    revert.error instanceof ApiError && revert.error.status === 409 ? revert.error : null;
  const diffs = describeChange(change.before, change.after, lookups);
  const isApply = change.kind === "apply";

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 gap-3">
          <input
            type="checkbox"
            className="mt-0.5 size-4 shrink-0 accent-brand-600"
            checked={marked}
            onChange={() => onToggle(change.document_id)}
            aria-label={`Dokument ${change.document_id} markieren`}
          />
          <div className="min-w-0">
            <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
              <Badge tone={isApply ? "success" : "neutral"}>
                {isApply ? "Übernommen" : "Rückgängig gemacht"}
              </Badge>
              <span className="truncate">{change.after.title}</span>
            </p>
            <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
              Dokument {change.document_id} · {dateTime.format(new Date(change.created_at))}
              {change.reverted_by != null && " · später rückgängig gemacht"}
            </p>
          </div>
        </div>
        {isApply && change.reverted_by == null && (
          <Button
            onClick={() => revert.mutate({ id: change.id })}
            disabled={revert.isPending}
            aria-label={`Änderung an Dokument ${change.document_id} rückgängig machen`}
          >
            <RotateCcw className="size-4" aria-hidden="true" />
            Rückgängig
          </Button>
        )}
      </div>
      {diffs.length > 0 && (
        <ul className="mt-3 space-y-1 text-sm">
          {diffs.map((d) => (
            <li key={d.label} className="flex flex-wrap items-center gap-2">
              <span className="w-24 shrink-0 text-xs text-zinc-500 dark:text-zinc-400">
                {d.label}
              </span>
              <span className="text-zinc-500 line-through decoration-zinc-400 dark:text-zinc-400">
                {d.before}
              </span>
              <ArrowRight className="size-3.5 text-zinc-400" aria-label="wird zu" />
              <span className="font-medium">{d.after}</span>
            </li>
          ))}
        </ul>
      )}
      {conflict && !confirmForce && (
        <Alert tone="warning" className="mt-3 flex-wrap justify-between">
          <span>{conflict.message}.</span>
          <Button
            variant="primary"
            onClick={() => {
              setConfirmForce(true);
              revert.mutate({ id: change.id, force: true });
            }}
          >
            Trotzdem zurücksetzen
          </Button>
        </Alert>
      )}
      {revert.error && !conflict && (
        <Alert tone="danger" className="mt-3">
          {revert.error.message}
        </Alert>
      )}
    </Card>
  );
}

type Diff = { label: string; before: string; after: string };

export function describeChange(
  before: DocumentState,
  after: DocumentState,
  lookups: Lookups | undefined,
): Diff[] {
  const names = lookups
    ? nameMaps(lookups)
    : { types: new Map(), correspondents: new Map(), tags: new Map() };
  const tags = (ids: number[]) =>
    ids
      .map((t) => nameOf(names.tags, t))
      .sort()
      .join(", ") || "–";
  const rows: Diff[] = [
    { label: "Titel", before: before.title, after: after.title },
    {
      label: "Dokumenttyp",
      before: nameOf(names.types, before.document_type_id),
      after: nameOf(names.types, after.document_type_id),
    },
    {
      label: "Absender",
      before: nameOf(names.correspondents, before.correspondent_id),
      after: nameOf(names.correspondents, after.correspondent_id),
    },
    { label: "Datum", before: formatDate(before.created), after: formatDate(after.created) },
    { label: "Tags", before: tags(before.tag_ids), after: tags(after.tag_ids) },
  ];
  return rows.filter((r) => r.before !== r.after);
}
