import { ArrowRight, RotateCcw } from "lucide-react";
import { useState } from "react";
import { ApiError, type Change, type DocumentState, type Lookups } from "@/api/client";
import { useChanges, useLookups, useRevertChange } from "@/api/queries";
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

  return (
    <>
      <PageHeader
        title="Verlauf"
        description="Jede Änderung, die paperless-pilot in Paperless geschrieben hat."
      />
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
            <ChangeCard change={change} lookups={lookups.data} />
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

function ChangeCard({ change, lookups }: { change: Change; lookups: Lookups | undefined }) {
  const revert = useRevertChange();
  const [confirmForce, setConfirmForce] = useState(false);
  const conflict =
    revert.error instanceof ApiError && revert.error.status === 409 ? revert.error : null;
  const diffs = describe(change.before, change.after, lookups);
  const isApply = change.kind === "apply";

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
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

export function describe(
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
