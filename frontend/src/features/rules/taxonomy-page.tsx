import { Download, Plus, RefreshCw, Trash2, Upload } from "lucide-react";
import { type ChangeEvent, useEffect, useId, useMemo, useRef, useState } from "react";
import type { PersonEntry, SyncItem, Taxonomy, TaxonomyEntry } from "@/api/client";
import { useSaveTaxonomy, useSyncTaxonomy, useTaxonomy } from "@/api/queries";
import { PageHeader } from "@/components/page-header";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

type Group = "document_types" | "persons" | "areas";

const SYNC_LABEL: Record<
  SyncItem["status"],
  { text: string; tone: "success" | "neutral" | "danger" }
> = {
  linked: { text: "in Paperless", tone: "success" },
  link_by_name: { text: "wird verknüpft", tone: "neutral" },
  missing: { text: "fehlt in Paperless", tone: "danger" },
  stale: { text: "in Paperless gelöscht", tone: "danger" },
};

export function TaxonomyPage() {
  const { data, error, isPending } = useTaxonomy();
  const save = useSaveTaxonomy();
  const sync = useSyncTaxonomy();
  const [draft, setDraft] = useState<Taxonomy | null>(null);
  const [importError, setImportError] = useState<string | null>(null);

  // Serverstand übernehmen, solange nichts bearbeitet wird.
  useEffect(() => {
    if (data)
      setDraft((current) => (current && isDirty(current, data.taxonomy) ? current : data.taxonomy));
  }, [data]);

  const dirty = useMemo(() => !!draft && !!data && isDirty(draft, data.taxonomy), [draft, data]);
  const duplicates = useMemo(() => (draft ? findDuplicates(draft) : []), [draft]);
  const pending = data?.sync.filter((i) => i.status !== "linked") ?? [];

  if (error) return <Alert tone="danger">{error.message}</Alert>;
  if (isPending || !draft || !data) return <p className="text-sm text-zinc-500">Lädt …</p>;

  const update = (group: Group, entries: TaxonomyEntry[] | PersonEntry[]) =>
    setDraft({ ...draft, [group]: entries });

  const onImport = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    try {
      const imported = normalizeTaxonomy(JSON.parse(await file.text()) as Partial<Taxonomy>);
      setImportError(null);
      save.mutate(imported, { onSuccess: (state) => setDraft(state.taxonomy) });
    } catch {
      setImportError("Die Datei ist kein gültiges JSON.");
    }
  };

  return (
    <div className="pb-24">
      <PageHeader
        title="Regeln"
        description="Welche Dokumenttypen, Personen und Lebensbereiche paperless-pilot vergeben darf."
        actions={<ImportExport onImport={onImport} />}
      />

      <div className="space-y-4">
        {!data.configured && (
          <Alert tone="info">
            Noch keine Taxonomie gespeichert. Lege die Einträge an oder importiere eine Sicherung –
            erst dann kann paperless-pilot Dokumente einordnen.
          </Alert>
        )}
        {importError && <Alert tone="danger">{importError}</Alert>}
        {save.error && <Alert tone="danger">Nicht gespeichert: {save.error.message}</Alert>}
        {sync.error && <Alert tone="danger">Abgleich fehlgeschlagen: {sync.error.message}</Alert>}
        {pending.length > 0 && !dirty && (
          <Alert tone="warning" className="flex-wrap justify-between">
            <span>
              {pending.length === 1
                ? "1 Eintrag ist noch nicht mit Paperless verknüpft"
                : `${pending.length} Einträge sind noch nicht mit Paperless verknüpft`}
              : {pending.map((i) => i.name).join(", ")}
            </span>
            <Button variant="primary" onClick={() => sync.mutate()} disabled={sync.isPending}>
              <RefreshCw className="size-4" aria-hidden="true" />
              In Paperless anlegen
            </Button>
          </Alert>
        )}

        <EntrySection
          title="Dokumenttypen"
          hint="Was für ein Schriftstück? Die Beschreibung hilft dem Modell bei Grenzfällen."
          group="document_types"
          entries={draft.document_types}
          sync={data.sync}
          onChange={(entries) => update("document_types", entries)}
        />
        <EntrySection
          title="Personen"
          hint="Wen betrifft das Dokument? Aliase sind weitere Schreibweisen, z. B. voller Name."
          group="persons"
          entries={draft.persons}
          sync={data.sync}
          onChange={(entries) => update("persons", entries)}
        />
        <EntrySection
          title="Lebensbereiche"
          hint="Zu welchem Bereich gehört das Dokument? Genau einer pro Dokument."
          group="areas"
          entries={draft.areas}
          sync={data.sync}
          onChange={(entries) => update("areas", entries)}
        />
        <AdvancedSettings draft={draft} onChange={setDraft} sync={data.sync} />
      </div>

      {dirty && (
        <div className="fixed inset-x-0 bottom-0 z-10 border-t border-zinc-200 bg-white/95 px-4 py-3 backdrop-blur md:left-60 dark:border-zinc-800 dark:bg-zinc-900/95">
          <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3">
            <p className="text-sm">
              {duplicates.length > 0
                ? `Doppelte Namen: ${duplicates.join(", ")}`
                : "Ungespeicherte Änderungen"}
            </p>
            <div className="flex gap-2">
              <Button onClick={() => setDraft(data.taxonomy)}>Verwerfen</Button>
              <Button
                variant="primary"
                onClick={() => save.mutate(draft)}
                disabled={save.isPending || duplicates.length > 0}
              >
                Speichern
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function EntrySection({
  title,
  hint,
  group,
  entries,
  sync,
  onChange,
}: {
  title: string;
  hint: string;
  group: Group;
  entries: (TaxonomyEntry | PersonEntry)[];
  sync: SyncItem[];
  onChange: (entries: (TaxonomyEntry | PersonEntry)[]) => void;
}) {
  const isPersons = group === "persons";
  const set = (index: number, patch: Partial<PersonEntry>) =>
    onChange(entries.map((e, i) => (i === index ? { ...e, ...patch } : e)));
  const headingId = useId();

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle id={headingId}>{title}</CardTitle>
          <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">{hint}</p>
        </div>
        <Button
          onClick={() =>
            onChange([
              ...entries,
              isPersons
                ? { name: "", description: "", aliases: [] }
                : { name: "", description: "" },
            ])
          }
          aria-label={`${title}: Eintrag hinzufügen`}
        >
          <Plus className="size-4" aria-hidden="true" />
          Hinzufügen
        </Button>
      </CardHeader>
      <CardContent>
        {entries.length === 0 ? (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">Noch keine Einträge.</p>
        ) : (
          <ul aria-labelledby={headingId} className="divide-y divide-zinc-100 dark:divide-zinc-800">
            {entries.map((entry, index) => {
              const item = sync.find((s) => s.group === group && s.name === entry.name);
              const label = item ? SYNC_LABEL[item.status] : null;
              return (
                // Einträge haben keine stabile ID; Index-Schlüssel ist hier bewusst (biome.json)
                <li
                  key={index}
                  className="grid gap-2 py-3 md:grid-cols-[12rem_1fr_auto] md:items-center"
                >
                  <Input
                    aria-label={`${title}: Name`}
                    placeholder="Name"
                    value={entry.name}
                    onChange={(e) => set(index, { name: e.target.value })}
                  />
                  {isPersons ? (
                    <div className="grid gap-2 sm:grid-cols-2">
                      <Input
                        aria-label="Aliase"
                        placeholder="Aliase, durch Komma getrennt"
                        value={((entry as PersonEntry).aliases ?? []).join(", ")}
                        onChange={(e) =>
                          set(index, {
                            aliases: e.target.value
                              .split(",")
                              .map((a) => a.trimStart())
                              .filter((a, i, all) => a || i === all.length - 1),
                          })
                        }
                      />
                      <Input
                        aria-label="Hinweis"
                        placeholder="Hinweis, z. B. Kind, Arbeitnehmerin"
                        value={entry.description ?? ""}
                        onChange={(e) => set(index, { description: e.target.value })}
                      />
                    </div>
                  ) : (
                    <Input
                      aria-label={`${title}: Beschreibung`}
                      placeholder="Beschreibung für das Modell"
                      value={entry.description ?? ""}
                      onChange={(e) => set(index, { description: e.target.value })}
                    />
                  )}
                  <div className="flex items-center justify-between gap-2 md:justify-end">
                    {label && <Badge tone={label.tone}>{label.text}</Badge>}
                    <Button
                      onClick={() => onChange(entries.filter((_, i) => i !== index))}
                      aria-label={`${entry.name || "Eintrag"} entfernen`}
                    >
                      <Trash2 className="size-4" aria-hidden="true" />
                    </Button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function AdvancedSettings({
  draft,
  onChange,
  sync,
}: {
  draft: Taxonomy;
  onChange: (taxonomy: Taxonomy) => void;
  sync: SyncItem[];
}) {
  const status = draft.status;
  const id = useId();
  const statusLabels = {
    todo: "Wartet auf Auslesen",
    review: "Vorschlag liegt vor",
    done: "Übernommen",
    error: "Fehler",
  } as const;

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Erweitert</CardTitle>
          <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
            Status-Tags, Ausschluss von Sammel-Korrespondenten und Posteingang.
          </p>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {(Object.keys(statusLabels) as (keyof typeof statusLabels)[]).map((key) => {
            const item = sync.find((s) => s.group === "status" && s.name === status[key].name);
            return (
              <div key={key} className="space-y-1 text-sm">
                <span className="flex items-center justify-between gap-2 text-zinc-600 dark:text-zinc-300">
                  <label htmlFor={`${id}-${key}`}>{statusLabels[key]}</label>
                  {item && item.status !== "linked" && (
                    <Badge tone="danger">{SYNC_LABEL[item.status].text}</Badge>
                  )}
                </span>
                <Input
                  id={`${id}-${key}`}
                  value={status[key].name}
                  onChange={(e) =>
                    onChange({
                      ...draft,
                      status: { ...status, [key]: { ...status[key], name: e.target.value } },
                    })
                  }
                />
              </div>
            );
          })}
        </div>
        <div className="space-y-1 text-sm">
          <label htmlFor={`${id}-exclude`} className="text-zinc-600 dark:text-zinc-300">
            Korrespondenten ausschließen (regulärer Ausdruck)
          </label>
          <Input
            id={`${id}-exclude`}
            className="font-mono"
            value={draft.correspondent_exclude_pattern ?? ""}
            onChange={(e) => onChange({ ...draft, correspondent_exclude_pattern: e.target.value })}
          />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="size-4 accent-brand-600"
            checked={draft.remove_inbox_tag_on_accept ?? true}
            onChange={(e) => onChange({ ...draft, remove_inbox_tag_on_accept: e.target.checked })}
          />
          Posteingangs-Tag beim Übernehmen entfernen
        </label>
      </CardContent>
    </Card>
  );
}

function ImportExport({ onImport }: { onImport: (event: ChangeEvent<HTMLInputElement>) => void }) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <div className="flex gap-2">
      <Button onClick={() => input.current?.click()}>
        <Upload className="size-4" aria-hidden="true" />
        Importieren
      </Button>
      <input
        ref={input}
        type="file"
        accept="application/json,.json"
        className="hidden"
        aria-label="Sicherung importieren"
        onChange={onImport}
      />
      <a
        href="/api/taxonomy/export"
        className="inline-flex h-8 items-center gap-2 rounded-lg px-3 text-sm font-medium text-zinc-700 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800"
      >
        <Download className="size-4" aria-hidden="true" />
        Exportieren
      </a>
    </div>
  );
}

const DEFAULT_STATUS: Taxonomy["status"] = {
  todo: { name: "ai:todo", description: "" },
  review: { name: "ai:prüfen", description: "" },
  done: { name: "ai:fertig", description: "" },
  error: { name: "ai:fehler", description: "" },
};

/** Ergänzt fehlende Felder, z. B. aus einer von Hand geschriebenen Sicherung. */
export function normalizeTaxonomy(partial: Partial<Taxonomy>): Taxonomy {
  const entry = (e: Partial<TaxonomyEntry>) => ({
    ...e,
    name: e.name ?? "",
    description: e.description ?? "",
  });
  return {
    document_types: (partial.document_types ?? []).map(entry),
    persons: (partial.persons ?? []).map((p) => ({ ...entry(p), aliases: p.aliases ?? [] })),
    areas: (partial.areas ?? []).map(entry),
    status: { ...DEFAULT_STATUS, ...partial.status },
    correspondent_exclude_pattern: partial.correspondent_exclude_pattern ?? "^o_",
    remove_inbox_tag_on_accept: partial.remove_inbox_tag_on_accept ?? true,
  };
}

function isDirty(a: Taxonomy, b: Taxonomy): boolean {
  return JSON.stringify(a) !== JSON.stringify(b);
}

export function findDuplicates(taxonomy: Taxonomy): string[] {
  const seen = new Set<string>();
  const duplicates = new Set<string>();
  const check = (names: string[]) => {
    for (const name of names) {
      const key = name.trim().toLocaleLowerCase("de");
      if (!key) continue;
      if (seen.has(key)) duplicates.add(name.trim());
      seen.add(key);
    }
  };
  check(taxonomy.document_types?.map((e) => e.name) ?? []);
  seen.clear();
  check([
    ...(taxonomy.persons ?? []).map((e) => e.name),
    ...(taxonomy.areas ?? []).map((e) => e.name),
    ...Object.values(taxonomy.status ?? {}).map((e) => e.name),
  ]);
  return [...duplicates];
}
