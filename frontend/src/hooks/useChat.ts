import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";

export type Character = {
  id: string; name: string; portrait_url: string | null; summary: string; has_description: boolean;
  profile_state: "missing" | "current" | "outdated"; conversation_count: number; last_activity_at: string | null;
};
export type Conversation = {
  id: string; character_id: string; title: string; created_at: string; last_activity_at: string; archived_at: string | null;
  learning_reviewed_at: string | null; learning_failure_code: string | null;
};
export type MessageStatus = "complete" | "streaming" | "incomplete" | "cancelled" | "failed";
export type Message = {
  id: string; role: "user" | "assistant"; content: string; status: MessageStatus; reply_to: string | null;
  provider: string | null; model: string | null; first_token_ms: number | null; duration_ms: number | null;
  failure_code: string | null; used_memory_ids: string[] | null; created_at: string; client_message_id: string | null;
};
export type ChatStatus = {
  available: boolean; reason: string | null; character_id?: string | null; provider: string; is_sample: boolean; model_busy: boolean;
  profile_state?: "missing" | "current" | "outdated"; profile_outdated: boolean; limits: { max_user_chars: number; context_messages: number };
};
export type Evidence = { message_id: string; quote: string };
export type Candidate = {
  id: string; statement: string; category: string; scope: string; evidence_type: string; supporting: Evidence[];
  status: string; conversation_id: string | null; created_at: string;
};
export type Memory = {
  id: string; statement: string; category: string; scope: string; evidence_type: string; supporting: Evidence[];
  source_deleted: boolean; edited: boolean; pinned: boolean; status: "active" | "superseded"; superseded_by: string | null;
  conversation_id: string | null; created_at: string; updated_at: string;
};
export type Proposal = {
  id: string; memory_id: string | null; section: string; current_text: string | null; proposed_text: string;
  kind: string; evidence: string[]; status: string; created_at: string; resolved_at: string | null;
};
export type Revision = { id: string; profile: Record<string, unknown>; reason: string; proposal_id: string | null; created_at: string };
export type LearningPref = {
  enabled: boolean; enabled_at: string | null; disabled_at: string | null; accepted_disclosure_version: string | null;
  current_disclosure_version: string;
};
export type ReviewState = {
  state: "idle" | "running"; reviewed_at: string | null; failure_code: string | null; candidates: Candidate[];
};

const P = "/api/v1";
export const K = {
  status: ["chat-status"], convs: ["conversations"], chars: ["characters"], msgs: (id: string) => ["messages", id],
  pref: ["learning-pref"], cands: ["candidates"], mems: ["memories"], props: ["proposals"], revs: ["revisions"],
  review: (id: string) => ["review", id],
};

export const useCharacters = () =>
  useQuery({ queryKey: K.chars, queryFn: async () => (await api.get<{ characters: Character[] }>(`${P}/characters`)).characters });
/** Status for ONE character: its profile state is per character. */
export const useChatStatus = (characterId: string | null) =>
  useQuery({ queryKey: [...K.status, characterId ?? ""], retry: 1,
    queryFn: () => api.get<ChatStatus>(`${P}/chat/status${characterId ? `?character_id=${encodeURIComponent(characterId)}` : ""}`) });
export const useConversations = () =>
  useQuery({ queryKey: K.convs, queryFn: async () => (await api.get<{ conversations: Conversation[] }>(`${P}/conversations`)).conversations });
export function useMessages(id: string | null) {
  return useQuery({
    queryKey: K.msgs(id ?? ""), enabled: !!id,
    queryFn: () => api.get<{ messages: Message[]; generating: boolean }>(`${P}/conversations/${id}/messages`),
    // Another tab (or an earlier request) may still be writing a reply: follow the real server state.
    refetchInterval: (q) => (q.state.data?.generating ? 2000 : false),
  });
}
export function useCreateConversation() {
  const qc = useQueryClient();
  return useMutation({
    // The character is named explicitly; the server still verifies it is one of this user's own.
    mutationFn: (characterId: string) => api.post<Conversation>(`${P}/conversations`, { character_id: characterId }),
    onSuccess: () => { for (const k of [K.convs, K.chars]) qc.invalidateQueries({ queryKey: k }); },
  });
}
export function useRenameConversation() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (v: { id: string; title: string }) => api.patch(`${P}/conversations/${v.id}`, { title: v.title }), onSuccess: () => qc.invalidateQueries({ queryKey: K.convs }) });
}
export function useDeleteConversation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { id: string; deleteMemories: boolean }) => api.del(`${P}/conversations/${v.id}?delete_memories=${v.deleteMemories}`),
    onSuccess: () => { for (const k of [K.convs, K.chars, K.mems, K.cands]) qc.invalidateQueries({ queryKey: k }); },
  });
}

export const useLearningPref = () => useQuery({ queryKey: K.pref, queryFn: () => api.get<LearningPref>(`${P}/learning/preference`) });
export function useSetLearning() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { enabled: boolean; disclosure?: string }) => api.put<LearningPref>(`${P}/learning/preference`, { enabled: v.enabled, disclosure_version: v.disclosure }),
    onSuccess: (d) => qc.setQueryData(K.pref, d),
  });
}
export function useReviewState(id: string | null) {
  return useQuery({
    queryKey: K.review(id ?? ""), enabled: !!id, queryFn: () => api.get<ReviewState>(`${P}/conversations/${id}/learning`),
    refetchInterval: (q) => (q.state.data?.state === "running" ? 2000 : false),
  });
}
export function useStartReview() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post(`${P}/conversations/${id}/learning/review`),
    onSuccess: (_d, id) => qc.invalidateQueries({ queryKey: K.review(id) }),
  });
}

export const useCandidates = () => useQuery({ queryKey: K.cands, queryFn: async () => (await api.get<{ candidates: Candidate[] }>(`${P}/memory/candidates`)).candidates });
export const useMemories = () => useQuery({ queryKey: K.mems, queryFn: async () => (await api.get<{ memories: Memory[] }>(`${P}/memories`)).memories });
export const useProposals = () => useQuery({ queryKey: K.props, queryFn: async () => (await api.get<{ proposals: Proposal[] }>(`${P}/profile-proposals`)).proposals });
export const useRevisions = () => useQuery({ queryKey: K.revs, queryFn: async () => (await api.get<{ revisions: Revision[] }>(`${P}/profile-revisions`)).revisions });

function useRefresh<V, R>(fn: (v: V) => Promise<R>, keys: readonly (readonly unknown[])[]) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSettled: () => { for (const k of keys) qc.invalidateQueries({ queryKey: k as unknown[] }); } });
}
export const useApprove = () =>
  useRefresh((v: { id: string; statement?: string; resolution?: "keep_both" | "replace" }) =>
    api.post<{ memory: Memory; profile_proposal: Proposal | null }>(`${P}/memory/candidates/${v.id}/approve`, { statement: v.statement, resolution: v.resolution }),
  [K.cands, K.mems, K.props]);
export const useReject = () =>
  useRefresh((v: { id: string; reason: "wrong" | "not_relevant" | "private" }) => api.post(`${P}/memory/candidates/${v.id}/reject`, { reason: v.reason }), [K.cands]);
export const useEditMemory = () =>
  useRefresh((v: { id: string; statement?: string; scope?: string; pinned?: boolean }) => {
    const { id, ...body } = v;
    return api.patch(`${P}/memories/${id}`, body);
  }, [K.mems]);
export const useForget = () =>
  useRefresh((v: { id: string; incorrect: boolean }) => api.del(`${P}/memories/${v.id}?incorrect=${v.incorrect}`), [K.mems, K.props]);
export const useProposeFromMemory = () =>
  useRefresh((v: { id: string; section: string }) => api.post(`${P}/memories/${v.id}/profile-proposal`, { section: v.section }), [K.props]);
export const useResolveProposal = () =>
  useRefresh((v: { id: string; action: "accept" | "reject" | "defer"; text?: string }) =>
    api.post(`${P}/profile-proposals/${v.id}/resolve`, { action: v.action, text: v.text }), [K.props, K.revs, ["me"]]);
