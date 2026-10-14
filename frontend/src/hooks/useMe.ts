import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Me, type Question, type Twin } from "../lib/api";

export const ME_KEY = ["me"];

export function useMe(enabled = true) {
  return useQuery({ queryKey: ME_KEY, queryFn: () => api.get<Me>("/api/v1/me"), enabled, retry: 1 });
}

export function useQuestionnaire() {
  return useQuery({
    queryKey: ["questionnaire"],
    queryFn: () => api.get<{ questions: Question[] }>("/api/v1/onboarding/questionnaire"),
    staleTime: Infinity,
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
  useRefreshingMutation((b: { name?: string; about?: string; communication?: object; appearance?: object }) =>
    api.put<Twin>("/api/v1/twin", b),
  );
export const useSavePersonality = () =>
  useRefreshingMutation((answers: Record<string, string | string[]>) => api.put<Twin>("/api/v1/twin/personality", { answers }));
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
