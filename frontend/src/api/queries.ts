import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ApiError,
  api,
  type HostRules,
  type MetadataValues,
  type SystemStatus,
  type Taxonomy,
  unwrap,
} from "./client";

export const STATUS_REFRESH_MS = 15_000;

export const queryKeys = {
  status: ["system-status"] as const,
  taxonomy: ["taxonomy"] as const,
  lookups: ["lookups"] as const,
  hosts: ["hosts"] as const,
  jobs: ["jobs"] as const,
  suggestions: ["suggestions"] as const,
  changes: ["changes"] as const,
  lessons: ["lessons"] as const,
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

export function useSuggestions() {
  return useQuery({
    queryKey: queryKeys.suggestions,
    queryFn: () => unwrap(api.GET("/api/suggestions")),
  });
}

export function useSuggestion(id: number | null) {
  return useQuery({
    queryKey: [...queryKeys.suggestions, id],
    queryFn: () =>
      unwrap(
        api.GET("/api/suggestions/{suggestion_id}", {
          params: { path: { suggestion_id: id ?? 0 } },
        }),
      ),
    enabled: id != null,
  });
}

function useSuggestionAction<T, R>(action: (args: T) => Promise<R>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: action,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.suggestions });
      void client.invalidateQueries({ queryKey: queryKeys.lessons });
      void client.invalidateQueries({ queryKey: queryKeys.status });
      void client.invalidateQueries({ queryKey: queryKeys.changes });
      void client.invalidateQueries({ queryKey: queryKeys.lookups });
    },
  });
}

export function useAcceptSuggestion() {
  return useSuggestionAction(
    ({ id, values, force = false }: { id: number; values: MetadataValues; force?: boolean }) =>
      unwrap(
        api.POST("/api/suggestions/{suggestion_id}/accept", {
          params: { path: { suggestion_id: id } },
          body: { values, force },
        }),
      ),
  );
}

export function useRejectSuggestion() {
  return useSuggestionAction((id: number) =>
    unwrap(
      api.POST("/api/suggestions/{suggestion_id}/reject", {
        params: { path: { suggestion_id: id } },
        body: { reason: null },
      }),
    ),
  );
}

export function useReextractSuggestion() {
  return useSuggestionAction((id: number) =>
    unwrap(
      api.POST("/api/suggestions/{suggestion_id}/reextract", {
        params: { path: { suggestion_id: id } },
      }),
    ),
  );
}

export function useChanges() {
  return useInfiniteQuery({
    queryKey: queryKeys.changes,
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/api/changes", {
          params: {
            query: { limit: CHANGES_PAGE, ...(pageParam ? { before_id: pageParam } : {}) },
          },
        }),
      ),
    initialPageParam: 0,
    getNextPageParam: (last) =>
      last.length === CHANGES_PAGE ? last[last.length - 1]?.id : undefined,
  });
}

export const CHANGES_PAGE = 50;

export function useRevertChange() {
  return useSuggestionAction(({ id, force = false }: { id: number; force?: boolean }) =>
    unwrap(
      api.POST("/api/changes/{change_id}/revert", {
        params: { path: { change_id: id } },
        body: { force },
      }),
    ),
  );
}

export function useLessons() {
  return useQuery({
    queryKey: queryKeys.lessons,
    queryFn: () => unwrap(api.GET("/api/lessons")),
  });
}

export function useForgetLesson() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      // 204 ohne Inhalt – deshalb nicht über unwrap
      const { response } = await api.DELETE("/api/lessons/{lesson_id}", {
        params: { path: { lesson_id: id } },
      });
      if (!response.ok) {
        throw new ApiError(`Backend antwortet mit HTTP ${response.status}`, response.status, null);
      }
    },
    onSuccess: () => void client.invalidateQueries({ queryKey: queryKeys.lessons }),
  });
}
