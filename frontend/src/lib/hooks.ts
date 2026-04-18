"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";

export type Me = {
  id: number;
  github_id: number;
  github_login: string;
  email: string | null;
};

export type ApiKey = {
  id: number;
  provider: "anthropic" | "openai" | "google" | "ollama";
  masked_hint: string;
  created_at: string;
};

export function useMe() {
  return useQuery<Me | null>({
    queryKey: ["me"],
    queryFn: () => apiFetch<Me | null>("/auth/me"),
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<void>("/auth/logout", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["me"] }),
  });
}

export function useKeys(enabled: boolean) {
  return useQuery<ApiKey[]>({
    queryKey: ["keys"],
    queryFn: () => apiFetch<ApiKey[]>("/keys"),
    enabled,
  });
}

export function useCreateKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { provider: ApiKey["provider"]; key: string }) =>
      apiFetch<ApiKey>("/keys", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["keys"] }),
  });
}

export function useDeleteKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiFetch<void>(`/keys/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["keys"] }),
  });
}

export type SuspectedFile = {
  file_path: string;
  line_range: string;
  rationale: string;
};

export type DuplicateCandidate = {
  issue_number: number;
  rationale: string;
  confidence: number;
};

export type Card = {
  id: number;
  repo_full_name: string;
  repo_default_branch?: string | null;
  issue_number: number;
  status: string;
  classification: string | null;
  confidence?: number | null;
  rationale?: string | null;
  draft_comment?: string | null;
  proposed_action?: string | null;
  proposed_labels?: string[] | null;
  suspected_files?: SuspectedFile[] | null;
  duplicates?: DuplicateCandidate[] | null;
  reproduction_verdict?:
    | "reproduced"
    | "not_reproduced"
    | "insufficient_info"
    | "unsupported_language"
    | "sandbox_error"
    | null;
  reproduction_log?: string | null;
  final_comment?: string | null;
  created_at: string;
};

export type Repo = {
  id: number;
  full_name: string;
  default_branch: string;
  primary_language: string | null;
  indexing_status: string;
  indexed_at: string | null;
};

export function useCards(enabled: boolean) {
  return useQuery<Card[]>({
    queryKey: ["cards"],
    queryFn: () => apiFetch<Card[]>("/cards"),
    enabled,
  });
}

export function useRepos(enabled: boolean) {
  return useQuery<Repo[]>({
    queryKey: ["repos"],
    queryFn: () => apiFetch<Repo[]>("/repos"),
    enabled,
  });
}

export type TestKeyResult = {
  ok: boolean;
  provider: ApiKey["provider"];
  model: string | null;
  sample: string | null;
  latency_ms: number | null;
  error: string | null;
};

export function useTestKey() {
  return useMutation({
    mutationFn: (provider: ApiKey["provider"]) =>
      apiFetch<TestKeyResult>("/llm/test", {
        method: "POST",
        body: JSON.stringify({ provider }),
      }),
  });
}

export function useApproveCard() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      apiFetch<Card>(`/cards/${id}/approve`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cards"] }),
  });
}

export function useSkipCard() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      apiFetch<Card>(`/cards/${id}/skip`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cards"] }),
  });
}

export function useEditCard() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: { id: number; draft_comment: string }) =>
      apiFetch<Card>(`/cards/${args.id}`, {
        method: "PATCH",
        body: JSON.stringify({ draft_comment: args.draft_comment }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cards"] }),
  });
}
