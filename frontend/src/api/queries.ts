import { useQuery } from "@tanstack/react-query";
import { api, type SystemStatus } from "./client";

export const STATUS_REFRESH_MS = 15_000;

export async function fetchSystemStatus(): Promise<SystemStatus> {
  const { data, response } = await api.GET("/api/system/status");
  if (!data) {
    throw new Error(`Backend antwortet mit HTTP ${response.status}`);
  }
  return data;
}

export function useSystemStatus() {
  return useQuery({
    queryKey: ["system-status"],
    queryFn: fetchSystemStatus,
    refetchInterval: STATUS_REFRESH_MS,
  });
}
