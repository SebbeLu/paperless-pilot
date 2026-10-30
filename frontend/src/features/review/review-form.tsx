import { AlertTriangle, CheckCircle2, Info } from "lucide-react";
import { type ReactNode, useId } from "react";
import type { FieldCheck, Lookups, MetadataValues, Taxonomy } from "@/api/client";
import { Input, Select } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export const NEW_CORRESPONDENT = "new";

type Props = {
  values: MetadataValues;
  live: MetadataValues;
  checks: Record<string, FieldCheck>;
  taxonomy: Taxonomy;
  lookups: Lookups;
  onChange: (values: MetadataValues) => void;
};

/** Felder eines Vorschlags: aktueller Wert, Vorschlag (bearbeitbar), Prüfergebnis mit Beleg. */
export function ReviewForm({ values, live, checks, taxonomy, lookups, onChange }: Props) {
  const set = (patch: Partial<MetadataValues>) => onChange({ ...values, ...patch });
  const names = nameMaps(lookups);
  const types = taxonomy.document_types.filter((t) => t.paperless_id != null);
  const areas = taxonomy.areas.filter((a) => a.paperless_id != null);
  const correspondents = lookups.correspondents.filter((c) => !c.excluded);
  const correspondentValue =
    values.correspondent_id != null
      ? String(values.correspondent_id)
      : values.new_correspondent != null
        ? NEW_CORRESPONDENT
        : "";

  return (
    <div className="space-y-4">
      <Field
        label="Dokumenttyp"
        check={checks.document_type}
        current={nameOf(names.types, live.document_type_id)}
        changed={values.document_type_id !== live.document_type_id}
        render={(id) => (
          <Select
            id={id}
            value={values.document_type_id ?? ""}
            onChange={(e) =>
              set({ document_type_id: e.target.value ? Number(e.target.value) : null })
            }
          >
            <option value="">– keiner –</option>
            {types.map((t) => (
              <option key={t.paperless_id} value={t.paperless_id ?? ""}>
                {t.name}
              </option>
            ))}
          </Select>
        )}
      />
      <Field
        label="Absender"
        check={checks.correspondent}
        current={nameOf(names.correspondents, live.correspondent_id)}
        changed={values.correspondent_id !== live.correspondent_id || !!values.new_correspondent}
        render={(id) => (
          <div className="space-y-2">
            <Select
              id={id}
              value={correspondentValue}
              onChange={(e) => {
                const value = e.target.value;
                if (value === NEW_CORRESPONDENT)
                  set({
                    correspondent_id: null,
                    new_correspondent: values.new_correspondent || "",
                  });
                else
                  set({ correspondent_id: value ? Number(value) : null, new_correspondent: null });
              }}
            >
              <option value="">– keiner –</option>
              {values.new_correspondent != null && (
                <option value={NEW_CORRESPONDENT}>
                  Neu anlegen: {values.new_correspondent || "…"}
                </option>
              )}
              {values.new_correspondent == null && (
                <option value={NEW_CORRESPONDENT}>Neu anlegen …</option>
              )}
              {correspondents.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
            {correspondentValue === NEW_CORRESPONDENT && (
              <Input
                aria-label="Name des neuen Absenders"
                value={values.new_correspondent ?? ""}
                onChange={(e) => set({ new_correspondent: e.target.value })}
              />
            )}
          </div>
        )}
      />
      <Field
        label="Datum"
        check={checks.created}
        current={formatDate(live.created)}
        changed={values.created !== live.created}
        render={(id) => (
          <Input
            id={id}
            type="date"
            value={values.created ?? ""}
            onChange={(e) => set({ created: e.target.value || null })}
          />
        )}
      />
      <Field
        label="Personen"
        check={checks.persons}
        current={live.person_tag_ids.map((t) => nameOf(names.tags, t)).join(", ") || "–"}
        changed={!sameSet(values.person_tag_ids, live.person_tag_ids)}
        render={() => (
          <div className="flex flex-wrap gap-1.5">
            {taxonomy.persons
              .filter((p) => p.paperless_id != null)
              .map((person) => {
                const id = person.paperless_id as number;
                const active = values.person_tag_ids.includes(id);
                return (
                  <button
                    key={id}
                    type="button"
                    aria-pressed={active}
                    onClick={() =>
                      set({
                        person_tag_ids: active
                          ? values.person_tag_ids.filter((t) => t !== id)
                          : [...values.person_tag_ids, id],
                      })
                    }
                    className={cn(
                      "rounded-full border px-3 py-1 text-sm transition-colors",
                      active
                        ? "border-brand-600 bg-brand-600 text-white"
                        : "border-zinc-300 text-zinc-700 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800",
                    )}
                  >
                    {person.name}
                  </button>
                );
              })}
          </div>
        )}
      />
      <Field
        label="Lebensbereich"
        check={checks.area}
        current={nameOf(names.tags, live.area_tag_id)}
        changed={values.area_tag_id !== live.area_tag_id}
        render={(id) => (
          <Select
            id={id}
            value={values.area_tag_id ?? ""}
            onChange={(e) => set({ area_tag_id: e.target.value ? Number(e.target.value) : null })}
          >
            <option value="">– keiner –</option>
            {areas.map((a) => (
              <option key={a.paperless_id} value={a.paperless_id ?? ""}>
                {a.name}
              </option>
            ))}
          </Select>
        )}
      />
      <Field
        label="Titel"
        check={checks.title}
        current={live.title ?? "–"}
        changed={values.title !== live.title}
        render={(id) => (
          <Input
            id={id}
            value={values.title ?? ""}
            onChange={(e) => set({ title: e.target.value })}
          />
        )}
      />
    </div>
  );
}

function Field({
  label,
  check,
  current,
  changed,
  render,
}: {
  label: string;
  check: FieldCheck | undefined;
  current: string;
  changed: boolean;
  render: (id: string) => ReactNode;
}) {
  const id = useId();
  return (
    <div
      data-warn={check?.status === "warn" || undefined}
      className={cn("rounded-lg p-2 -m-2", changed && "bg-brand-50/60 dark:bg-zinc-800/40")}
    >
      <div className="mb-1 flex items-baseline justify-between gap-2">
        <label htmlFor={id} className="text-sm font-medium">
          {label}
        </label>
        <span className="truncate text-xs text-zinc-500 dark:text-zinc-400" title={current}>
          bisher: {current}
        </span>
      </div>
      {render(id)}
      {check && (check.message || check.evidence) && <CheckLine check={check} />}
    </div>
  );
}

function CheckLine({ check }: { check: FieldCheck }) {
  const Icon =
    check.status === "warn" ? AlertTriangle : check.status === "ok" ? CheckCircle2 : Info;
  return (
    <p
      className={cn(
        "mt-1 flex items-start gap-1.5 text-xs",
        check.status === "warn"
          ? "text-amber-700 dark:text-amber-300"
          : "text-zinc-500 dark:text-zinc-400",
      )}
    >
      <Icon className="mt-px size-3.5 shrink-0" aria-hidden="true" />
      <span>
        {check.message}
        {check.evidence && (
          <span className="block italic text-zinc-500 dark:text-zinc-400">„{check.evidence}“</span>
        )}
      </span>
    </p>
  );
}

type NameMaps = {
  types: Map<number, string>;
  correspondents: Map<number, string>;
  tags: Map<number, string>;
};

export function nameMaps(lookups: Lookups): NameMaps {
  return {
    types: new Map(lookups.document_types.map((t) => [t.id, t.name])),
    correspondents: new Map(lookups.correspondents.map((c) => [c.id, c.name])),
    tags: new Map(lookups.tags.map((t) => [t.id, t.name])),
  };
}

export function nameOf(map: Map<number, string>, id: number | null | undefined): string {
  if (id == null) return "–";
  return map.get(id) ?? `#${id}`;
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "–";
  const [year, month, day] = iso.split("-");
  return `${day}.${month}.${year}`;
}

function sameSet(a: number[], b: number[]): boolean {
  return a.length === b.length && a.every((x) => b.includes(x));
}
