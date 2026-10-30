import { Pause, Play, RefreshCw } from "lucide-react";
import { type FormEvent, useEffect, useId, useState } from "react";
import type { HostRules, HostState } from "@/api/client";
import { useHosts, useRefreshHosts, useUpdateHostRules } from "@/api/queries";
import { PageHeader } from "@/components/page-header";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

type Status = { label: string; tone: "success" | "neutral" | "danger"; dot: string };

export function hostStatus(host: HostState): Status {
  if (!host.online) return { label: "Offline", tone: "danger", dot: "bg-rose-500" };
  if (host.busy_document_id != null)
    return { label: "Arbeitet", tone: "success", dot: "bg-emerald-500 animate-pulse" };
  if (!host.has_model) return { label: "Modell fehlt", tone: "danger", dot: "bg-rose-500" };
  if (host.rules?.paused) return { label: "Pausiert", tone: "neutral", dot: "bg-zinc-400" };
  if (host.decision?.allowed) return { label: "Bereit", tone: "success", dot: "bg-emerald-500" };
  return { label: "Wartet", tone: "neutral", dot: "bg-amber-500" };
}

export function HostsPage() {
  const { data, error, isPending } = useHosts();
  const refresh = useRefreshHosts();

  return (
    <>
      <PageHeader
        title="Rechner & Modelle"
        description="Wann welcher Ollama-Rechner Dokumente auslesen darf."
        actions={
          <Button onClick={() => refresh.mutate()} disabled={refresh.isPending}>
            <RefreshCw
              className={cn("size-4", refresh.isPending && "animate-spin")}
              aria-hidden="true"
            />
            Jetzt prüfen
          </Button>
        }
      />
      {error && <Alert tone="danger">{error.message}</Alert>}
      {isPending && <p className="text-sm text-zinc-500">Lädt …</p>}
      {data && data.length === 0 && (
        <Alert tone="info">
          Noch kein Ollama-Rechner eingetragen. Trage ihn in <code>PILOT_OLLAMA_HOSTS</code> ein.
        </Alert>
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        {data?.map((host) => (
          <HostCard key={host.name} host={host} />
        ))}
      </div>
    </>
  );
}

function HostCard({ host }: { host: HostState }) {
  const status = hostStatus(host);
  const update = useUpdateHostRules();
  const rules = host.rules ?? {};
  const save = (next: HostRules) => update.mutate({ name: host.name, rules: next });

  return (
    <Card>
      <CardHeader>
        <div className="min-w-0">
          <CardTitle>{host.name}</CardTitle>
          <p className="mt-0.5 truncate text-xs text-zinc-500 dark:text-zinc-400">{host.url}</p>
        </div>
        <Badge tone={status.tone}>
          <span aria-hidden="true" className={cn("size-1.5 rounded-full", status.dot)} />
          {status.label}
        </Badge>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm">{explain(host)}</p>

        <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
          <Fact label="Modell" value={host.model} warn={host.online && !host.has_model} />
          <Fact label="Ausgelesen" value={`${host.processed ?? 0} Dokumente`} />
          <Fact
            label="Zuletzt"
            value={
              host.last_duration_ms != null ? `${Math.round(host.last_duration_ms / 1000)} s` : "–"
            }
          />
        </dl>
        {host.online && !host.has_model && (
          <Alert tone="warning">
            Modell fehlt auf diesem Rechner. Dort ausführen: <code>ollama pull {host.model}</code>
          </Alert>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant={rules.paused ? "primary" : "ghost"}
            onClick={() => save({ ...rules, paused: !rules.paused })}
            disabled={update.isPending}
          >
            {rules.paused ? (
              <Play className="size-4" aria-hidden="true" />
            ) : (
              <Pause className="size-4" aria-hidden="true" />
            )}
            {rules.paused ? "Fortsetzen" : "Pausieren"}
          </Button>
        </div>

        <RulesForm host={host} onSave={save} saving={update.isPending} />
        {update.error && <Alert tone="danger">{update.error.message}</Alert>}
      </CardContent>
    </Card>
  );
}

function explain(host: HostState): string {
  if (!host.online) return `Nicht erreichbar${host.error ? `: ${host.error}` : ""}.`;
  if (host.busy_document_id != null) return `Liest gerade Dokument ${host.busy_document_id} aus.`;
  return host.decision?.reason ?? "";
}

function Fact({ label, value, warn = false }: { label: string; value: string; warn?: boolean }) {
  return (
    <div>
      <dt className="text-xs text-zinc-500 dark:text-zinc-400">{label}</dt>
      <dd className={cn("truncate font-medium", warn && "text-rose-600")}>{value}</dd>
    </div>
  );
}

function RulesForm({
  host,
  onSave,
  saving,
}: {
  host: HostState;
  onSave: (rules: HostRules) => void;
  saving: boolean;
}) {
  const [form, setForm] = useState(() => toForm(host.rules ?? {}));
  const id = useId();
  useEffect(() => setForm(toForm(host.rules ?? {})), [host.rules]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    onSave({
      ...host.rules,
      window: form.window.trim() || null,
      idle_entity: form.idle_entity.trim() || null,
      idle_minutes: Number(form.idle_minutes) || 10,
      block_entity: form.block_entity.trim() || null,
    });
  };
  const field = (key: keyof typeof form, label: string, placeholder: string, extra = {}) => (
    <label className="space-y-1 text-sm" htmlFor={`${id}-${key}`}>
      <span className="text-zinc-600 dark:text-zinc-300">{label}</span>
      <Input
        id={`${id}-${key}`}
        value={form[key]}
        placeholder={placeholder}
        onChange={(e) => setForm({ ...form, [key]: e.target.value })}
        {...extra}
      />
    </label>
  );

  return (
    <form
      onSubmit={submit}
      className="space-y-3 border-t border-zinc-100 pt-4 dark:border-zinc-800"
    >
      <p className="text-xs text-zinc-500 dark:text-zinc-400">
        Freigabe, wenn das Zeitfenster offen ist <em>oder</em> Home Assistant Leerlauf meldet. Ohne
        Regeln arbeitet der Rechner immer.
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        {field("window", "Zeitfenster", "z. B. 20:00-07:00")}
        {field("idle_entity", "Leerlauf-Entität (Home Assistant)", "binary_sensor.mac_active")}
        {field("idle_minutes", "Leerlauf mindestens (Minuten)", "10", { type: "number", min: 1 })}
        {field("block_entity", "Sperr-Entität, z. B. Spiel läuft", "binary_sensor.pc_spiel")}
      </div>
      {host.ha_available === false && (
        <Alert tone="warning">
          Home Assistant ist nicht erreichbar – es gilt nur das Zeitfenster.
        </Alert>
      )}
      {Object.entries(host.entity_states ?? {}).map(([entity, state]) => (
        <p key={entity} className="text-xs text-zinc-500 dark:text-zinc-400">
          {entity}: <span className="font-medium">{state.state}</span>
        </p>
      ))}
      <div className="flex justify-end">
        <Button type="submit" variant="primary" disabled={saving}>
          Regeln speichern
        </Button>
      </div>
    </form>
  );
}

function toForm(rules: HostRules) {
  return {
    window: rules.window ?? "",
    idle_entity: rules.idle_entity ?? "",
    idle_minutes: String(rules.idle_minutes ?? 10),
    block_entity: rules.block_entity ?? "",
  };
}
