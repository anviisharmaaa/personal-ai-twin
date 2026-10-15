import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type CharacterState, type Me, type Twin } from "../lib/api";
import { config } from "../lib/config";

export const ME_KEY = ["me"];

export function useMe(enabled = true) {
  return useQuery({
    queryKey: ME_KEY, queryFn: () => api.get<Me>("/api/v1/me"), enabled, retry: 1,
    // While the server reports a generation in progress, ask again every 2 s. Stops by itself when it is idle.
    refetchInterval: (q) => (q.state.data?.character?.analysis?.state === "running" ? 2000 : false),
  });
}

/** Public readiness probe: tells the UI up front whether the server can run AI analysis. */
export function useReady() {
  return useQuery({
    queryKey: ["ready"],
    queryFn: async () => {
      const r = await fetch(`${config.apiUrl}/ready`);
      if (!r.ok) throw new Error("not ready");
      return (await r.json()) as { ai_provider?: string; configured?: { supabase?: boolean; ai?: boolean } };
    },
    retry: false,
    staleTime: 60_000,
  });
}

function useRefreshingMutation<V, R>(fn: (v: V) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => qc.invalidateQueries({ queryKey: ME_KEY }) });
}

export const useGrantConsent = (version: string) =>
  useRefreshingMutation<void, unknown>(() => api.post("/api/v1/consents/ai-processing", { version }));
export const useWithdrawConsent = () => useRefreshingMutation<void, void>(() => api.del("/api/v1/consents/ai-processing"));
export const useSaveTwin = () =>
  useRefreshingMutation((b: { name?: string; about?: string; appearance?: object }) =>
    api.put<Twin>("/api/v1/twin", b),
  );
export const useSaveCharacter = () =>
  useRefreshingMutation((v: { description: string; baseVersion: number }) =>
    api.put<{ twin: Twin; character: CharacterState }>("/api/v1/twin/character", {
      description: v.description, base_version: v.baseVersion,
    }),
  );
/** Starts an analysis. The server answers at once (202) and keeps working; progress is read from /me. */
export const useAnalyzeCharacter = () =>
  useRefreshingMutation((version: number) =>
    api.post<{ character: CharacterState; cached: boolean }>("/api/v1/twin/character/analyze", { version }),
  );
export const useCompleteStep = () =>
  useRefreshingMutation((step: string) => api.post(`/api/v1/onboarding/steps/${step}/complete`));
export const useSaveProfile = () =>
  useRefreshingMutation((b: { display_name?: string; timezone?: string }) => api.put("/api/v1/me/profile", b));
export const useUploadPortrait = () =>
  useRefreshingMutation((v: { blob: Blob; other: boolean; permission: boolean }) => {
    const f = new FormData();
    f.append("file", v.blob, "portrait.jpg");
    f.append("depicts_someone_else", String(v.other));
    f.append("permission_confirmed", String(v.permission));
    return api.upload<Twin>("/api/v1/twin/portrait", f);
  });
export const useDeletePortrait = () => useRefreshingMutation<void, void>(() => api.del("/api/v1/twin/portrait"));
