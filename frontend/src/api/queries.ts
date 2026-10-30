import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type SystemStatus, type Taxonomy, unwrap } from "./client";

export const STATUS_REFRESH_MS = 15_000;

export const queryKeys = {
  status: ["system-status"] as const,
  taxonomy: ["taxonomy"] as const,
  lookups: ["lookups"] as const,
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
