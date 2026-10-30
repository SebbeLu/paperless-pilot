import { Construction } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { Card } from "@/components/ui/card";

export function PlaceholderPage({
  title,
  description,
  phase,
}: {
  title: string;
  description: string;
  phase: number;
}) {
  return (
    <>
      <PageHeader title={title} description={description} />
      <Card className="flex flex-col items-center gap-3 px-6 py-16 text-center">
        <Construction className="size-8 text-zinc-400" aria-hidden="true" />
        <p className="font-medium">Kommt in Phase {phase}</p>
        <p className="max-w-sm text-sm text-zinc-500 dark:text-zinc-400">
          Dieser Bereich ist im Konzept geplant und wird im Fahrplan schrittweise gebaut.
        </p>
      </Card>
    </>
  );
}
