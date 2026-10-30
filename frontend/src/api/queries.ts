import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type HostRules, type SystemStatus, type Taxonomy, unwrap } from "./client";

export const STATUS_REFRESH_MS = 15_000;

export const queryKeys = {
  status: ["system-status"] as const,
  taxonomy: ["taxonomy"] as const,
  lookups: ["lookups"] as const,
  hosts: ["hosts"] as const,
  jobs: ["jobs"] as const,
  suggestions: ["suggestions"] as const,
  changes: ["changes"] as const,
};

export async function fetchSystemStatus(): Promise<SystemStatus> {
  return unwrap(api.GET("/api/system/status"));
}

export function useSystemStatus() {
  return useQuery({
    queryKey: queryKeys.status,
    queryFn: fetchSystemStatus,
    refetchInterval: STATUS_REFRESH_MS,
  });
}

export function useTaxonomy() {
  return useQuery({
    queryKey: queryKeys.taxonomy,
    queryFn: () => unwrap(api.GET("/api/taxonomy")),
  });
}

export function useSaveTaxonomy() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (taxonomy: Taxonomy) => unwrap(api.PUT("/api/taxonomy", { body: taxonomy })),
    onSuccess: (state) => {
      client.setQueryData(queryKeys.taxonomy, state);
      void client.invalidateQueries({ queryKey: queryKeys.lookups });
    },
  });
}

export function useSyncTaxonomy() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/taxonomy/sync")),
    onSuccess: (state) => {
      client.setQueryData(queryKeys.taxonomy, state);
      void client.invalidateQueries({ queryKey: queryKeys.lookups });
    },
  });
}

export function useLookups() {
  return useQuery({
    queryKey: queryKeys.lookups,
    queryFn: () => unwrap(api.GET("/api/paperless/lookups")),
    staleTime: 60_000,
  });
}

export function useHosts() {
  return useQuery({
    queryKey: queryKeys.hosts,
    queryFn: () => unwrap(api.GET("/api/hosts")),
    refetchInterval: 30_000,
  });
}

export function useRefreshHosts() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/hosts/refresh")),
    onSuccess: (hosts) => client.setQueryData(queryKeys.hosts, hosts),
  });
}

export function useUpdateHostRules() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ name, rules }: { name: string; rules: HostRules }) =>
      unwrap(api.PUT("/api/hosts/{name}/rules", { params: { path: { name } }, body: rules })),
    onSuccess: () => void client.invalidateQueries({ queryKey: queryKeys.hosts }),
  });
}

export function useJobs(status?: "queued" | "running" | "succeeded" | "failed") {
  return useQuery({
    queryKey: [...queryKeys.jobs, status ?? "all"],
    queryFn: () => unwrap(api.GET("/api/jobs", { params: { query: status ? { status } : {} } })),
  });
}

export function useEnqueueInbox() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      unwrap(api.POST("/api/jobs/enqueue", { body: { scope: "inbox", document_ids: [] } })),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.status });
      void client.invalidateQueries({ queryKey: queryKeys.jobs });
    },
  });
}

export function useRetryJob() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (jobId: number) =>
      unwrap(api.POST("/api/jobs/{job_id}/retry", { params: { path: { job_id: jobId } } })),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.jobs });
      void client.invalidateQueries({ queryKey: queryKeys.status });
    },
  });
}
