"use client";

import { useState } from "react";
import { KeyRound, Wallet } from "lucide-react";

import { AppShell, EmptyState, PageHeader, Skeleton } from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api";
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
  const signedIn = Boolean(me.data);
  const keys = useKeys(signedIn);
  const createKey = useCreateKey();
  const deleteKey = useDeleteKey();

  const [provider, setProvider] = useState<ApiKey["provider"]>("anthropic");
  const [keyValue, setKeyValue] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const testKey = useTestKey();
  const [testResults, setTestResults] = useState<Record<number, TestKeyResult>>({});
  const usage = useMonthlyUsage(signedIn);

  return (
    <AppShell me={me.data ?? null}>
      {!signedIn ? (
        <EmptyState
          icon={KeyRound}
          title="Sign in to manage settings"
          description="LLM API keys are encrypted at rest with Fernet and never leave this deployment."
        />
      ) : (
        <>
          <PageHeader
            title="Settings"
            description="LLM keys, spend, and per-repo budget. Keys are Fernet-encrypted at rest."
          />

          <SpendCard loading={usage.isLoading} data={usage.data} />

          <section className="mt-6 rounded-lg border bg-card p-6 shadow-sm">
            <div className="mb-1 flex items-center gap-2">
              <KeyRound className="h-4 w-4 text-muted-foreground" />
              <h2 className="text-base font-medium">Add an LLM API key</h2>
            </div>
            <p className="text-sm text-muted-foreground">
              Saving a new key for a provider replaces the previous one.
            </p>
            <form
              className="mt-4 grid gap-4 sm:grid-cols-[180px_1fr_auto]"
              onSubmit={async (e) => {
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
                  if (err instanceof ApiError) setFormError(err.message);
                  else if (err instanceof Error) setFormError(err.message);
                  else setFormError("failed to save key");
                }
              }}
            >
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
            {formError && (
              <p className="mt-3 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
                {formError}
              </p>
            )}
          </section>

          <section className="mt-6 rounded-lg border bg-card p-6 shadow-sm">
            <h2 className="mb-3 text-base font-medium">Stored keys</h2>
            {keys.isLoading ? (
              <Skeleton className="h-16 w-full" />
            ) : keys.data && keys.data.length > 0 ? (
              <ul className="divide-y">
                {keys.data.map((k) => {
                  const result = testResults[k.id];
                  return (
                    <li key={k.id} className="flex flex-col gap-2 py-3">
                      <div className="flex items-center justify-between">
                        <div>
                          <div className="font-medium capitalize">{k.provider}</div>
                          <div className="font-mono text-sm text-muted-foreground">
                            {k.masked_hint}
                          </div>
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
                          className={`rounded-md px-3 py-1.5 text-sm ${
                            result.ok
                              ? "bg-muted/40 text-muted-foreground"
                              : "bg-destructive/10 text-destructive"
                          }`}
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
              <p className="text-sm text-muted-foreground">No keys saved yet.</p>
            )}
          </section>
        </>
      )}
    </AppShell>
  );
}

function SpendCard({
  loading,
  data,
}: {
  loading: boolean;
  data:
    | {
        total_spent_usd: number;
        month_start_utc: string;
        repos: {
          repo_id: number;
          repo_full_name: string;
          monthly_budget_usd: number;
          spent_usd: number;
          is_exhausted: boolean;
        }[];
      }
    | undefined;
}) {
  return (
    <section className="rounded-lg border bg-card p-6 shadow-sm">
      <div className="mb-1 flex items-center gap-2">
        <Wallet className="h-4 w-4 text-muted-foreground" />
        <h2 className="text-base font-medium">Spend this month</h2>
      </div>
      <p className="text-sm text-muted-foreground">
        Monthly budgets are per-repo and reset at UTC month start. Exhausted repos still
        get classify + comment; dedup, retrieval, and reproduction skip until next month.
      </p>
      {loading ? (
        <Skeleton className="mt-4 h-16 w-full" />
      ) : data && data.repos.length > 0 ? (
        <div className="mt-4 space-y-3">
          <div className="text-sm">
            Total spent: <strong>${data.total_spent_usd.toFixed(4)}</strong> since{" "}
            {new Date(data.month_start_utc).toLocaleDateString(undefined, {
              month: "long",
              year: "numeric",
            })}
          </div>
          <ul className="divide-y">
            {data.repos.map((r) => {
              const pct = r.monthly_budget_usd > 0 ? Math.min(100, (r.spent_usd / r.monthly_budget_usd) * 100) : 0;
              return (
                <li key={r.repo_id} className="flex items-center justify-between gap-4 py-2.5">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium">{r.repo_full_name}</div>
                    <div className="mt-1.5 h-1.5 w-56 overflow-hidden rounded-full bg-muted">
                      <div
                        className={`h-full ${r.is_exhausted ? "bg-destructive" : "bg-primary"}`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                  <div className="shrink-0 text-right text-xs">
                    <div className="text-muted-foreground">
                      ${r.spent_usd.toFixed(4)} / ${r.monthly_budget_usd.toFixed(2)}
                    </div>
                    {r.is_exhausted && (
                      <span className="mt-1 inline-block rounded-full border border-destructive/40 bg-destructive/10 px-2 py-0.5 text-[10px] font-medium text-destructive">
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
        <p className="mt-4 text-sm text-muted-foreground">
          No repos installed yet, or no LLM calls have been made this month.
        </p>
      )}
    </section>
  );
}
