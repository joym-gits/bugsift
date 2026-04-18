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
  budget_limited?: boolean;
  final_comment?: string | null;
  created_at: string;
};

export type RepoUsage = {
  repo_id: number;
  repo_full_name: string;
  monthly_budget_usd: number;
  spent_usd: number;
  remaining_usd: number;
  is_exhausted: boolean;
};

export type MonthlyUsage = {
  month_start_utc: string;
  total_spent_usd: number;
  repos: RepoUsage[];
};

export function useMonthlyUsage(enabled: boolean) {
  return useQuery<MonthlyUsage>({
    queryKey: ["usage", "this-month"],
    queryFn: () => apiFetch<MonthlyUsage>("/usage/this-month"),
    enabled,
  });
}

export type Repo = {
  id: number;
  full_name: string;
  default_branch: string;
  primary_language: string | null;
  indexing_status: string;
  indexed_at: string | null;
};

export type CardFilters = {
  status?: string;
  classification?: string;
  verdict?: string;
  limit?: number;
};

function cardsPath(filters: CardFilters): string {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.classification) params.set("classification", filters.classification);
  if (filters.verdict) params.set("verdict", filters.verdict);
  if (filters.limit) params.set("limit", String(filters.limit));
  const qs = params.toString();
  return qs ? `/cards?${qs}` : "/cards";
}

export function useCards(enabled: boolean, filters: CardFilters = {}) {
  return useQuery<Card[]>({
    queryKey: ["cards", filters],
    queryFn: () => apiFetch<Card[]>(cardsPath(filters)),
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

export type AppStatus = {
  configured: boolean;
  name?: string | null;
  slug?: string | null;
  html_url?: string | null;
  tunnel_url?: string | null;
  tunnel_running?: boolean;
};

export function useAppStatus(enabled: boolean, pollMs: number | false = false) {
  return useQuery<AppStatus>({
    queryKey: ["app-status"],
    queryFn: () => apiFetch<AppStatus>("/github/app/manifest/status"),
    enabled,
    refetchInterval: pollMs,
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

export function useRerunCard() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      apiFetch<{ status: string }>(`/cards/${id}/rerun`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cards"] }),
  });
}
