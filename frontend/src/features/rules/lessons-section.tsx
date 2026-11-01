import { Trash2 } from "lucide-react";
import type { Lesson, NamedValues } from "@/api/client";
import { useForgetLesson, useLessons } from "@/api/queries";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDate } from "@/features/review/review-form";

const FIELD_LABELS: Record<string, string> = {
  document_type: "Dokumenttyp",
  correspondent: "Absender",
  created: "Datum",
  persons: "Personen",
  area: "Lebensbereich",
  title: "Titel",
};

/** Korrekturen, die das Modell bei ähnlichen Dokumenten als Beispiel bekommt. */
export function LessonsSection() {
  const lessons = useLessons();
  const forget = useForgetLesson();
  const items = lessons.data ?? [];

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Gelernte Korrekturen</CardTitle>
          <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
            Was du beim Übernehmen korrigierst, bekommt das Modell bei ähnlichen Dokumenten als
            Beispiel. Eine falsche Korrektur kannst du hier vergessen lassen.
          </p>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {forget.error && <Alert tone="danger">Nicht vergessen: {forget.error.message}</Alert>}
        {lessons.isSuccess && items.length === 0 && (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">Noch keine Korrekturen.</p>
        )}
        <ul className="divide-y divide-zinc-200 dark:divide-zinc-800">
          {items.map((lesson) => (
            <li key={lesson.id} className="flex items-start justify-between gap-3 py-2">
              <div className="min-w-0 space-y-0.5 text-sm">
                <p className="font-medium">
                  Dokument {lesson.document_id}
                  {lesson.correct.correspondent && ` · ${lesson.correct.correspondent}`}
                </p>
                {lesson.corrected.map((field) => (
                  <p key={field}>
                    {FIELD_LABELS[field] ?? field}: {valueText(lesson.correct, field)}{" "}
                    <span className="text-zinc-500 dark:text-zinc-400">
                      statt {valueText(lesson.proposed, field)}
                    </span>
                  </p>
                ))}
                <p className="truncate text-xs text-zinc-500 dark:text-zinc-400">
                  {lesson.excerpt}
                </p>
              </div>
              <Button
                onClick={() => forget.mutate(lesson.id)}
                disabled={forget.isPending}
                aria-label={`Korrektur zu Dokument ${lesson.document_id} vergessen`}
              >
                <Trash2 className="size-4" aria-hidden="true" />
                Vergessen
              </Button>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

function valueText(values: NamedValues, field: Lesson["corrected"][number]): string {
  if (field === "created") return formatDate(values.created);
  if (field === "persons") return values.persons?.join(", ") || "keine";
  const value = values[field as keyof NamedValues];
  return typeof value === "string" && value ? value : "–";
}
