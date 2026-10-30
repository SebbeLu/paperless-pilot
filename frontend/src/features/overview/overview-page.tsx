import { Link } from "@tanstack/react-router";
import { AlertTriangle, FileText, Inbox, ListPlus, RefreshCw, Server } from "lucide-react";
import type { ReactNode } from "react";
import type { HostStatus, PaperlessStatus, SystemStatus } from "@/api/client";
import { useEnqueueInbox, useJobs, useRetryJob, useSystemStatus } from "@/api/queries";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const numberFormat = new Intl.NumberFormat("de-DE");
const timeFormat = new Intl.DateTimeFormat("de-DE", { timeStyle: "medium" });

export function OverviewPage() {
  const { data, error, isPending, isFetching, refetch, dataUpdatedAt } = useSystemStatus();

  return (
    <>
      <PageHeader
        title="Übersicht"
        description={
          dataUpdatedAt
            ? `Stand ${timeFormat.format(dataUpdatedAt)} · aktualisiert sich automatisch`
            : "Verbindungen zu Paperless und den Ollama-Rechnern"
        }
        actions={
          <Button
            onClick={() => void refetch()}
            disabled={isFetching}
            aria-label="Status neu laden"
          >
            <RefreshCw className={cn("size-4", isFetching && "animate-spin")} aria-hidden="true" />
            Aktualisieren
          </Button>
        }
      />

      {error && !data ? (
        <BackendError message={error.message} />
      ) : isPending ? (
        <LoadingState />
      ) : (
        <div className="space-y-8">
          <KeyFigures paperless={data.paperless} hosts={data.hosts} />
          <WorkSection status={data} />
          <section aria-labelledby="connections-heading">
            <h2
              id="connections-heading"
              className="mb-3 text-sm font-medium text-zinc-500 dark:text-zinc-400"
            >
              Verbindungen
            </h2>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              <PaperlessCard status={data.paperless} />
              {data.hosts.map((host) => (
                <HostCard key={host.name} host={host} />
              ))}
              {data.hosts.length === 0 && <NoHostsCard />}
            </div>
          </section>
        </div>
      )}
    </>
  );
}

function KeyFigures({ paperless, hosts }: { paperless: PaperlessStatus; hosts: HostStatus[] }) {
  const ready = hosts.filter((h) => h.reachable).length;
  const format = (n: number | null | undefined) => (n == null ? "–" : numberFormat.format(n));
  return (
    <dl className="grid gap-4 sm:grid-cols-3">
      <Figure
        icon={<FileText className="size-4" />}
        label="Dokumente"
        value={format(paperless.documents_total)}
      />
      <Figure
        icon={<Inbox className="size-4" />}
        label="Im Posteingang"
        value={format(paperless.documents_inbox)}
      />
      <Figure
        icon={<Server className="size-4" />}
        label="Rechner bereit"
        value={hosts.length ? `${ready} von ${hosts.length}` : "–"}
      />
    </dl>
  );
}

function WorkSection({ status }: { status: SystemStatus }) {
  const enqueue = useEnqueueInbox();
  const { queue, open_suggestions: open } = status;
  const waiting = queue.queued + queue.running;
  return (
    <section aria-labelledby="work-heading" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="work-heading" className="text-sm font-medium text-zinc-500 dark:text-zinc-400">
          Arbeitsstand
        </h2>
        <Button variant="primary" onClick={() => enqueue.mutate()} disabled={enqueue.isPending}>
          <ListPlus className="size-4" aria-hidden="true" />
          Posteingang einreihen
        </Button>
      </div>
      {enqueue.data && (
        <Alert tone="success">
          {enqueue.data.enqueued === 0
            ? "Keine neuen Dokumente im Posteingang."
            : `${enqueue.data.enqueued} Dokument(e) eingereiht – sie werden ausgelesen, sobald ein Rechner frei ist.`}
        </Alert>
      )}
      {enqueue.error && <Alert tone="danger">{enqueue.error.message}</Alert>}
      <dl className="grid gap-4 sm:grid-cols-3">
        <Card className="p-5">
          <dt className="text-sm text-zinc-500 dark:text-zinc-400">Zu prüfen</dt>
          <dd className="mt-2 flex items-baseline justify-between gap-2">
            <span className="text-3xl font-semibold tabular-nums tracking-tight">
              {numberFormat.format(open)}
            </span>
            {open > 0 && (
              <Link
                to="/pruefen"
                className="text-sm font-medium text-brand-700 hover:underline dark:text-brand-100"
              >
                Jetzt prüfen →
              </Link>
            )}
          </dd>
        </Card>
        <Figure
          icon={null}
          label={queue.running ? "Wartend (1 in Arbeit)" : "Wartend"}
          value={numberFormat.format(waiting)}
        />
        <Figure icon={null} label="Fehler" value={numberFormat.format(queue.failed)} />
      </dl>
      {queue.failed > 0 && <FailedJobs />}
    </section>
  );
}

function FailedJobs() {
  const { data } = useJobs("failed");
  const retry = useRetryJob();
  if (!data?.length) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Fehlgeschlagen</CardTitle>
      </CardHeader>
      <CardContent>
        <ul className="divide-y divide-zinc-100 text-sm dark:divide-zinc-800">
          {data.map((job) => (
            <li key={job.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <span>
                Dokument {job.document_id}
                <span className="block text-xs text-zinc-500 dark:text-zinc-400">
                  {job.last_error}
                </span>
              </span>
              <Button
                onClick={() => retry.mutate(job.id)}
                disabled={retry.isPending}
                aria-label={`Dokument ${job.document_id} erneut versuchen`}
              >
                Erneut versuchen
              </Button>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

function Figure({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <Card className="p-5">
      <dt className="flex items-center gap-2 text-sm text-zinc-500 dark:text-zinc-400">
        {icon && <span aria-hidden="true">{icon}</span>}
        {label}
      </dt>
      <dd className="mt-2 text-3xl font-semibold tabular-nums tracking-tight">{value}</dd>
    </Card>
  );
}

function PaperlessCard({ status }: { status: PaperlessStatus }) {
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Paperless-ngx</CardTitle>
          <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">Dokumentenarchiv</p>
        </div>
        <StatusBadge ok={status.reachable} okLabel="Verbunden" failLabel="Nicht erreichbar" />
      </CardHeader>
      <CardContent>
        {status.reachable ? (
          <p className="text-sm text-zinc-600 dark:text-zinc-300">Version {status.version}</p>
        ) : (
          <ErrorDetail
            text={status.error}
            hint={
              status.problem === "auth"
                ? "Paperless lehnt den API-Token ab. Token in der Konfiguration prüfen."
                : "Paperless antwortet nicht. Läuft der Container, und stimmt die Adresse?"
            }
          />
        )}
      </CardContent>
    </Card>
  );
}

function HostCard({ host }: { host: HostStatus }) {
  return (
    <Card>
      <CardHeader>
        <div className="min-w-0">
          <CardTitle>{host.name}</CardTitle>
          <p className="mt-0.5 truncate text-xs text-zinc-500 dark:text-zinc-400">{host.url}</p>
        </div>
        <StatusBadge ok={host.reachable} okLabel="Bereit" failLabel="Offline" />
      </CardHeader>
      <CardContent>
        {host.reachable ? (
          <>
            <p className="text-sm text-zinc-600 dark:text-zinc-300">Ollama {host.version}</p>
            {host.models && host.models.length > 0 ? (
              <ul className="mt-3 flex flex-wrap gap-1.5" aria-label={`Modelle auf ${host.name}`}>
                {host.models.map((model) => (
                  <li key={model}>
                    <Badge>{model}</Badge>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-3 text-sm text-zinc-500">Keine Modelle installiert.</p>
            )}
          </>
        ) : (
          <ErrorDetail
            text={host.error}
            hint={
              host.problem === "auth"
                ? "Ollama verweigert den Zugriff."
                : "Rechner aus oder Ollama nicht im Netz freigegeben (OLLAMA_HOST=0.0.0.0)."
            }
          />
        )}
      </CardContent>
    </Card>
  );
}

function NoHostsCard() {
  return (
    <Card className="flex flex-col justify-center p-5 text-sm text-zinc-500 dark:text-zinc-400">
      Noch kein Ollama-Rechner eingetragen. Trage ihn in <code>PILOT_OLLAMA_HOSTS</code> ein.
    </Card>
  );
}

function ErrorDetail({ text, hint }: { text: string | null | undefined; hint: string }) {
  return (
    <div className="space-y-1 text-sm">
      <p className="text-zinc-600 dark:text-zinc-300">{hint}</p>
      {text && <p className="break-words text-xs text-zinc-500 dark:text-zinc-400">{text}</p>}
    </div>
  );
}

function BackendError({ message }: { message: string }) {
  return (
    <Card role="alert" className="flex items-start gap-3 border-rose-200 p-5 dark:border-rose-900">
      <AlertTriangle className="mt-0.5 size-5 shrink-0 text-rose-600" aria-hidden="true" />
      <div>
        <p className="font-medium">Der paperless-pilot-Dienst antwortet nicht.</p>
        <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">{message}</p>
      </div>
    </Card>
  );
}

function LoadingState() {
  return (
    <div
      className="grid gap-4 sm:grid-cols-3"
      role="status"
      aria-busy="true"
      aria-label="Status wird geladen"
    >
      {[0, 1, 2].map((i) => (
        <div key={i} className="h-28 animate-pulse rounded-xl bg-zinc-200/60 dark:bg-zinc-800/60" />
      ))}
    </div>
  );
}
