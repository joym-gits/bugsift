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

export type RegressionSuspect = {
  commit_sha: string;
  short_sha: string;
  message_first_line: string;
  author_name: string | null;
  author_login: string | null;
  pushed_at_iso: string;
  pr_number: number | null;
  ref: string | null;
  overlapping_paths: string[];
};

export type Card = {
  id: number;
  repo_full_name: string;
  repo_default_branch?: string | null;
  issue_number: number | null;
  source?: "github" | "feedback";
  github_issue_number?: number | null;
  github_issue_url?: string | null;
  feedback_report_count?: number;
  status: string;
  classification: string | null;
  confidence?: number | null;
  rationale?: string | null;
  draft_comment?: string | null;
  proposed_action?: string | null;
  proposed_labels?: string[] | null;
  suspected_files?: SuspectedFile[] | null;
  duplicates?: DuplicateCandidate[] | null;
  regression_suspects?: RegressionSuspect[] | null;
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

export type CardFeedbackReport = {
  id: number;
  body_text: string;
  url: string | null;
  user_agent: string | null;
  app_version: string | null;
  console_log: string | null;
  reporter_hash: string | null;
  created_at: string;
};

export function useCardFeedbackReports(cardId: number | null, enabled: boolean) {
  return useQuery<CardFeedbackReport[]>({
    queryKey: ["card-feedback", cardId],
    queryFn: () =>
      apiFetch<CardFeedbackReport[]>(`/cards/${cardId}/reports`),
    enabled: enabled && cardId !== null,
  });
}

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

export type RepoBranch = { name: string; is_default: boolean };

export function useRepoBranches(repoId: number | null, enabled: boolean) {
  return useQuery<RepoBranch[]>({
    queryKey: ["repo-branches", repoId],
    queryFn: () => apiFetch<RepoBranch[]>(`/repos/${repoId}/branches`),
    enabled: enabled && repoId !== null,
    // Branches don't change often; keep them for a few minutes per repo
    // so switching back and forth in the form doesn't re-hit GitHub.
    staleTime: 5 * 60 * 1000,
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

export type AppDetails = {
  configured: boolean;
  github_app_id: number | null;
  name: string | null;
  slug: string | null;
  owner_login: string | null;
  html_url: string | null;
  client_id: string | null;
  client_secret_masked: string | null;
  webhook_secret_masked: string | null;
  private_key_fingerprint: string | null;
  created_at: string | null;
  updated_at: string | null;
  tunnel_url: string | null;
  tunnel_running: boolean;
  installations_count: number;
  repos_count: number;
};

export type InstallationOut = {
  id: number;
  github_installation_id: number;
  installed_at: string;
  suspended_at: string | null;
  repo_count: number;
};

export function useAppDetails(enabled: boolean) {
  return useQuery<AppDetails>({
    queryKey: ["app-details"],
    queryFn: () => apiFetch<AppDetails>("/github/app"),
    enabled,
  });
}

export function useInstallations(enabled: boolean) {
  return useQuery<InstallationOut[]>({
    queryKey: ["installations"],
    queryFn: () => apiFetch<InstallationOut[]>("/github/installations"),
    enabled,
  });
}

export function useDeleteApp() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<void>("/github/app/manifest", { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["app-status"] });
      qc.invalidateQueries({ queryKey: ["app-details"] });
      qc.invalidateQueries({ queryKey: ["installations"] });
    },
  });
}

export type HydrateResult = {
  added: number;
  skipped: number;
  installations: number;
};

export function useHydrateRepos() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<HydrateResult>("/repos/hydrate", { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["repos"] });
      qc.invalidateQueries({ queryKey: ["app-details"] });
      qc.invalidateQueries({ queryKey: ["installations"] });
    },
  });
}

export type BackfillResult = {
  repo_id: number;
  queued: boolean;
};

export type FeedbackApp = {
  id: number;
  name: string;
  public_key: string;
  default_repo_id: number | null;
  default_repo_full_name: string | null;
  default_repo_branch: string | null;
  target_branch: string | null;
  allowed_origins: string[] | null;
  created_at: string;
  report_count: number;
};

export function useFeedbackApps(enabled: boolean) {
  return useQuery<FeedbackApp[]>({
    queryKey: ["feedback-apps"],
    queryFn: () => apiFetch<FeedbackApp[]>("/feedback/apps"),
    enabled,
  });
}

export function useFeedbackApp(id: number | null, enabled: boolean) {
  return useQuery<FeedbackApp | null>({
    queryKey: ["feedback-app", id],
    queryFn: async () => {
      if (id === null) return null;
      const all = await apiFetch<FeedbackApp[]>("/feedback/apps");
      return all.find((a) => a.id === id) ?? null;
    },
    enabled: enabled && id !== null,
  });
}

export function useCreateFeedbackApp() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      name: string;
      default_repo_id?: number | null;
      allowed_origins?: string[] | null;
      target_branch?: string | null;
    }) =>
      apiFetch<FeedbackApp>("/feedback/apps", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["feedback-apps"] }),
  });
}

export function useUpdateFeedbackApp() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: {
      id: number;
      body: Partial<{
        name: string;
        default_repo_id: number | null;
        allowed_origins: string[] | null;
        target_branch: string | null;
      }>;
    }) =>
      apiFetch<FeedbackApp>(`/feedback/apps/${args.id}`, {
        method: "PATCH",
        body: JSON.stringify(args.body),
      }),
    onSuccess: (_data, args) => {
      qc.invalidateQueries({ queryKey: ["feedback-apps"] });
      qc.invalidateQueries({ queryKey: ["feedback-app", args.id] });
    },
  });
}

export function useDeleteFeedbackApp() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      apiFetch<void>(`/feedback/apps/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["feedback-apps"] }),
  });
}

export type RepoAnalysis = {
  id: number;
  repo_id: number;
  branch: string;
  status: "pending" | "running" | "ready" | "failed";
  structured_json: {
    summary?: string;
    components?: {
      name: string;
      path: string;
      role: string;
      citations?: string[];
    }[];
    entry_points?: { name: string; file: string; note?: string }[];
    dependencies?: string[];
    flows?: { name: string; description: string; mermaid?: string }[];
    mermaid_overview?: string;
  } | null;
  mermaid_src: string | null;
  overrides: string[];
  error_detail: string | null;
  generated_at: string | null;
  updated_at: string;
};

export function useAnalysis(
  appId: number | null,
  enabled: boolean,
  pollMs: number | false = false,
) {
  return useQuery<RepoAnalysis | null>({
    queryKey: ["analysis", appId],
    queryFn: () => apiFetch<RepoAnalysis | null>(`/feedback/apps/${appId}/analysis`),
    enabled: enabled && appId !== null,
    refetchInterval: pollMs,
  });
}

export function useKickAnalysis() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (appId: number) =>
      apiFetch<RepoAnalysis>(`/feedback/apps/${appId}/analyze`, { method: "POST" }),
    onSuccess: (_data, appId) =>
      qc.invalidateQueries({ queryKey: ["analysis", appId] }),
  });
}

export function useAddCorrection() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: { appId: number; note: string }) =>
      apiFetch<RepoAnalysis>(`/feedback/apps/${args.appId}/analysis/corrections`, {
        method: "POST",
        body: JSON.stringify({ note: args.note }),
      }),
    onSuccess: (_data, args) =>
      qc.invalidateQueries({ queryKey: ["analysis", args.appId] }),
  });
}

export function useBackfillRepo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (repoId: number) =>
      apiFetch<BackfillResult>(`/repos/${repoId}/backfill`, { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["cards"] });
      qc.invalidateQueries({ queryKey: ["repos"] });
    },
  });
}

export function useApproveCard() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      admin_note,
    }: {
      id: number;
      admin_note?: string | null;
    }) =>
      apiFetch<Card>(`/cards/${id}/approve`, {
        method: "POST",
        body: JSON.stringify(
          admin_note && admin_note.trim() ? { admin_note: admin_note.trim() } : {},
        ),
      }),
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
