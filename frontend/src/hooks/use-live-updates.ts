import { type QueryClient, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { queryKeys } from "@/api/queries";

const TOPICS = {
  jobs: [queryKeys.jobs, queryKeys.status],
  suggestions: [queryKeys.suggestions, queryKeys.status],
  changes: [queryKeys.changes],
  hosts: [queryKeys.hosts],
  taxonomy: [queryKeys.taxonomy, queryKeys.lookups],
} as const;

export function invalidateFor(client: QueryClient, topic: keyof typeof TOPICS) {
  for (const key of TOPICS[topic]) {
    void client.invalidateQueries({ queryKey: key });
  }
}

/** Hört auf Server-Sent Events und lädt betroffene Daten neu. */
export function useLiveUpdates() {
  const client = useQueryClient();
  useEffect(() => {
    if (typeof EventSource === "undefined") return;
    const source = new EventSource("/api/events");
    for (const topic of Object.keys(TOPICS) as (keyof typeof TOPICS)[]) {
      source.addEventListener(topic, () => invalidateFor(client, topic));
    }
    return () => source.close();
  }, [client]);
}
