"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { API_BASE_URL, ApiError } from "@/lib/api";
import {
  type ApiKey,
  type TestKeyResult,
  useCreateKey,
  useDeleteKey,
  useKeys,
  useMe,
  useMonthlyUsage,
  useTestKey,
} from "@/lib/hooks";

const PROVIDERS: ApiKey["provider"][] = ["anthropic", "openai", "google", "ollama"];

export default function SettingsPage() {
  const me = useMe();
  const keys = useKeys(Boolean(me.data));
  const createKey = useCreateKey();
  const deleteKey = useDeleteKey();

  const [provider, setProvider] = useState<ApiKey["provider"]>("anthropic");
  const [keyValue, setKeyValue] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const testKey = useTestKey();
  const [testResults, setTestResults] = useState<Record<number, TestKeyResult>>({});
  const usage = useMonthlyUsage(Boolean(me.data));

  if (me.isLoading) {
    return (
      <main className="container mx-auto py-16 text-muted-foreground">loading…</main>
    );
  }

  if (!me.data) {
    return (
      <main className="container mx-auto flex min-h-screen flex-col justify-center gap-6 py-16">
        <h1 className="text-3xl font-semibold tracking-tight">Settings</h1>
        <p className="text-muted-foreground">
          Sign in with GitHub to manage your API keys and repo settings.
        </p>
        <a
          href={`${API_BASE_URL}/auth/github/start`}
          className="inline-flex h-10 w-fit items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          Sign in with GitHub
        </a>
      </main>
    );
  }

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);
    if (!keyValue.trim()) {
      setFormError("paste the api key before saving");
      return;
    }
    try {
      await createKey.mutateAsync({ provider, key: keyValue.trim() });
      setKeyValue("");
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "failed to save key");
    }
  };

  return (
    <main className="container mx-auto flex flex-col gap-8 py-16">
      <header className="space-y-2">
        <h1 className="text-3xl font-semibold tracking-tight">Settings</h1>
        <p className="text-muted-foreground">
          Signed in as <strong>{me.data.github_login}</strong>. API keys are encrypted
          at rest with Fernet and never returned in plaintext.
        </p>
      </header>

      <section className="rounded-lg border bg-card p-6 shadow-sm">
        <h2 className="text-lg font-medium">Spend this month</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Monthly budgets are per-repo and reset at UTC month start. When a repo
          exhausts its budget, classify + comment still run but dedup, retrieval,
          and reproduction are skipped until next month.
        </p>
        {usage.isLoading ? (
          <p className="mt-3 text-sm text-muted-foreground">loading…</p>
        ) : usage.data && usage.data.repos.length > 0 ? (
          <div className="mt-4 space-y-2">
            <div className="text-sm">
              Total spent:{" "}
              <strong>${usage.data.total_spent_usd.toFixed(4)}</strong> since{" "}
              {new Date(usage.data.month_start_utc).toLocaleDateString(undefined, {
                month: "long",
                year: "numeric",
              })}
            </div>
            <ul className="divide-y">
              {usage.data.repos.map((r) => {
                const pct =
                  r.monthly_budget_usd > 0
                    ? Math.min(100, (r.spent_usd / r.monthly_budget_usd) * 100)
                    : 0;
                return (
                  <li key={r.repo_id} className="flex items-center justify-between gap-4 py-2 text-sm">
                    <div className="min-w-0">
                      <div className="truncate font-medium">{r.repo_full_name}</div>
                      <div className="h-1.5 w-48 overflow-hidden rounded-full bg-muted">
                        <div
                          className={`h-full ${r.is_exhausted ? "bg-destructive" : "bg-primary"}`}
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                    </div>
                    <div className="shrink-0 text-xs text-muted-foreground">
                      ${r.spent_usd.toFixed(4)} / ${r.monthly_budget_usd.toFixed(2)}
                      {r.is_exhausted && (
                        <span className="ml-2 rounded-full border border-destructive/40 bg-destructive/10 px-2 py-0.5 text-[10px] font-medium text-destructive">
                          exhausted
                        </span>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
        ) : (
          <p className="mt-3 text-sm text-muted-foreground">
            No repos installed yet, or no LLM calls have been made this month.
          </p>
        )}
      </section>

      <section className="rounded-lg border bg-card p-6 shadow-sm">
        <h2 className="text-lg font-medium">Add an LLM API key</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Saving a new key for a provider replaces the previous one.
        </p>
        <form className="mt-4 grid gap-4 sm:grid-cols-[180px_1fr_auto]" onSubmit={onSubmit}>
          <div className="space-y-1">
            <Label htmlFor="provider">Provider</Label>
            <select
              id="provider"
              value={provider}
              onChange={(e) => setProvider(e.target.value as ApiKey["provider"])}
              className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
            >
              {PROVIDERS.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="key">Key</Label>
            <Input
              id="key"
              type="password"
              autoComplete="off"
              placeholder="sk-..."
              value={keyValue}
              onChange={(e) => setKeyValue(e.target.value)}
            />
          </div>
          <div className="flex items-end">
            <Button type="submit" disabled={createKey.isPending}>
              {createKey.isPending ? "saving…" : "Save key"}
            </Button>
          </div>
        </form>
        {formError && <p className="mt-3 text-sm text-destructive">{formError}</p>}
      </section>

      <section className="rounded-lg border bg-card p-6 shadow-sm">
        <h2 className="text-lg font-medium">Stored keys</h2>
        {keys.isLoading ? (
          <p className="mt-2 text-sm text-muted-foreground">loading…</p>
        ) : keys.data && keys.data.length > 0 ? (
          <ul className="mt-4 divide-y">
            {keys.data.map((k) => {
              const result = testResults[k.id];
              return (
                <li key={k.id} className="flex flex-col gap-2 py-3">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="font-medium">{k.provider}</div>
                      <div className="text-sm text-muted-foreground">{k.masked_hint}</div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={testKey.isPending}
                        onClick={async () => {
                          const r = await testKey.mutateAsync(k.provider);
                          setTestResults((prev) => ({ ...prev, [k.id]: r }));
                        }}
                      >
                        {testKey.isPending && testKey.variables === k.provider
                          ? "testing…"
                          : "Test key"}
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => deleteKey.mutate(k.id)}
                        disabled={deleteKey.isPending}
                      >
                        Delete
                      </Button>
                    </div>
                  </div>
                  {result && (
                    <div
                      className={`text-sm ${result.ok ? "text-muted-foreground" : "text-destructive"}`}
                    >
                      {result.ok
                        ? `ok · ${result.model ?? "model"} · ${result.latency_ms}ms · “${result.sample}”`
                        : `failed: ${result.error}`}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="mt-2 text-sm text-muted-foreground">no keys saved yet.</p>
        )}
      </section>
    </main>
  );
}
