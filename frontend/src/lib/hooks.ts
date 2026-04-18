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
