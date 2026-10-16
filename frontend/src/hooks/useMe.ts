import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type CharacterState, type Gender, type UserIdentityRecord, type Me, type Twin } from "../lib/api";
import { config } from "../lib/config";
import { useCharacterScope, withCharacter } from "./characterScope";

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

export type CharacterDetail = { twin: Twin; character: CharacterState };

/** One character (the personal self-twin is read through /me instead). Follows a running analysis like /me does. */
export function useCharacter(id: string | null) {
  return useQuery({
    queryKey: ["character", id], enabled: !!id, retry: 1,
    queryFn: () => api.get<CharacterDetail>(`/api/v1/characters/${encodeURIComponent(id ?? "")}`),
    refetchInterval: (q) => (q.state.data?.character?.analysis?.state === "running" ? 2000 : false),
  });
}
export function useCreateCharacter() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (b: { name: string; description?: string; gender?: Gender; pronouns?: string }) => api.post<CharacterDetail>("/api/v1/characters", b),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["characters"] }),
  });
}

function useRefreshingMutation<V, R>(fn: (v: V) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    // Returned so the mutation stays pending until the refreshed state has arrived (callers rely on that ordering).
    onSuccess: () => Promise.all([ME_KEY, ["character"], ["characters"]].map((queryKey) => qc.invalidateQueries({ queryKey }))),
  });
}

export const useGrantConsent = (version: string) =>
  useRefreshingMutation<void, unknown>(() => api.post("/api/v1/consents/ai-processing", { version }));
export const useWithdrawConsent = () => useRefreshingMutation<void, void>(() => api.del("/api/v1/consents/ai-processing"));
export const useSaveTwin = () => {
  const id = useCharacterScope();
  return useRefreshingMutation((b: { name?: string; about?: string; appearance?: object }) =>
    api.put<Twin>(withCharacter("/api/v1/twin", id), b));
};
export const useSaveCharacter = () => {
  const id = useCharacterScope();
  return useRefreshingMutation((v: { description: string; baseVersion: number }) =>
    api.put<{ twin: Twin; character: CharacterState }>(withCharacter("/api/v1/twin/character", id), {
      description: v.description, base_version: v.baseVersion,
    }));
};
/** Starts an analysis. The server answers at once (202) and keeps working; progress is read from /me or the character. */
export const useAnalyzeCharacter = () => {
  const id = useCharacterScope();
  return useRefreshingMutation((version: number) =>
    api.post<{ character: CharacterState; cached: boolean }>(withCharacter("/api/v1/twin/character/analyze", id), { version }));
};
export const useCompleteStep = () =>
  useRefreshingMutation((step: string) => api.post(`/api/v1/onboarding/steps/${step}/complete`));
export const useSaveProfile = () =>
  useRefreshingMutation((b: { display_name?: string; timezone?: string } & Partial<UserIdentityRecord>) => api.put("/api/v1/me/profile", b));
export const useUploadPortrait = () => {
  const id = useCharacterScope();
  return useRefreshingMutation((v: { blob: Blob; other: boolean; permission: boolean }) => {
    const f = new FormData();
    f.append("file", v.blob, "portrait.jpg");
    f.append("depicts_someone_else", String(v.other));
    f.append("permission_confirmed", String(v.permission));
    return api.upload<Twin>(withCharacter("/api/v1/twin/portrait", id), f);
  });
};
export const useDeletePortrait = () => {
  const id = useCharacterScope();
  return useRefreshingMutation<void, void>(() => api.del(withCharacter("/api/v1/twin/portrait", id)));
};
