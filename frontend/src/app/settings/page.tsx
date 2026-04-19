"use client";

import { useState } from "react";
import { Hash, KeyRound, Trash2, Wallet } from "lucide-react";

import { AppShell, EmptyState, PageHeader, Skeleton } from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api";
import {
  type ApiKey,
  type SlackDestination,
  type SlackEvents,
  type TestKeyResult,
  useCreateKey,
  useCreateSlackDestination,
  useDeleteKey,
  useDeleteSlackDestination,
  useKeys,
  useMe,
  useMonthlyUsage,
  useSlackDestinations,
  useTestKey,
  useTestSlackDestination,
  useUpdateSlackDestination,
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

          <SlackSection signedIn={signedIn} />
        </>
      )}
    </AppShell>
  );
}

function SlackSection({ signedIn }: { signedIn: boolean }) {
  const destinations = useSlackDestinations(signedIn);
  const create = useCreateSlackDestination();
  const del = useDeleteSlackDestination();
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [channel, setChannel] = useState("");
  const [events, setEvents] = useState<SlackEvents>({
    new_card: true,
    approved: false,
    regression: true,
  });
  const [err, setErr] = useState<string | null>(null);

  return (
    <section className="mt-6 rounded-lg border bg-card p-6 shadow-sm">
      <div className="mb-1 flex items-center gap-2">
        <Hash className="h-4 w-4 text-muted-foreground" />
        <h2 className="text-base font-medium">Slack notifications</h2>
      </div>
      <p className="text-sm text-muted-foreground">
        Add an{" "}
        <a
          href="https://api.slack.com/messaging/webhooks"
          target="_blank"
          rel="noopener noreferrer"
          className="underline underline-offset-4"
        >
          Incoming Webhook
        </a>{" "}
        URL from your Slack workspace. bugsift will post a Block Kit
        message when the events you pick fire. Interactive buttons
        (approve-in-thread) are a v2 feature that needs a public
        bugsift URL.
      </p>

      <form
        className="mt-5 grid gap-4 sm:grid-cols-2"
        onSubmit={async (e) => {
          e.preventDefault();
          setErr(null);
          if (!name.trim() || !url.trim()) {
            setErr("name and webhook URL are required");
            return;
          }
          try {
            await create.mutateAsync({
              name: name.trim(),
              webhook_url: url.trim(),
              channel_hint: channel.trim() || null,
              events,
            });
            setName("");
            setUrl("");
            setChannel("");
            setEvents({
              new_card: true,
              approved: false,
              regression: true,
            });
          } catch (err2) {
            if (err2 instanceof ApiError) setErr(err2.message);
            else if (err2 instanceof Error) setErr(err2.message);
            else setErr("failed to save destination");
          }
        }}
      >
        <div className="space-y-1">
          <Label htmlFor="slack-name">Name</Label>
          <Input
            id="slack-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="triage-alerts"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="slack-channel">Channel (optional label)</Label>
          <Input
            id="slack-channel"
            value={channel}
            onChange={(e) => setChannel(e.target.value)}
            placeholder="#triage"
          />
        </div>
        <div className="sm:col-span-2 space-y-1">
          <Label htmlFor="slack-url">Webhook URL</Label>
          <Input
            id="slack-url"
            type="password"
            autoComplete="off"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://hooks.slack.com/services/T…/B…/…"
          />
        </div>
        <div className="sm:col-span-2 space-y-2">
          <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Notify on
          </div>
          <EventCheckboxes value={events} onChange={setEvents} />
        </div>
        <div className="sm:col-span-2 flex items-center gap-3">
          <Button type="submit" disabled={create.isPending}>
            {create.isPending ? "saving…" : "Add destination"}
          </Button>
          {err && (
            <span className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-1.5 text-xs text-destructive">
              {err}
            </span>
          )}
        </div>
      </form>

      <div className="mt-6">
        <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Connected destinations
        </h3>
        {destinations.isLoading ? (
          <Skeleton className="mt-3 h-16 w-full" />
        ) : (destinations.data ?? []).length === 0 ? (
          <p className="mt-3 text-sm text-muted-foreground">
            No destinations configured.
          </p>
        ) : (
          <ul className="mt-3 divide-y">
            {(destinations.data ?? []).map((d) => (
              <SlackDestinationRow
                key={d.id}
                destination={d}
                onDelete={(id) => del.mutate(id)}
              />
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

function EventCheckboxes({
  value,
  onChange,
}: {
  value: SlackEvents;
  onChange: (next: SlackEvents) => void;
}) {
  const row = (
    key: keyof SlackEvents,
    label: string,
    help: string,
  ) => (
    <label className="flex items-start gap-2 text-sm">
      <input
        type="checkbox"
        checked={value[key]}
        onChange={(e) => onChange({ ...value, [key]: e.target.checked })}
        className="mt-1"
      />
      <span>
        <div>{label}</div>
        <div className="text-xs text-muted-foreground">{help}</div>
      </span>
    </label>
  );

  return (
    <div className="grid gap-2 sm:grid-cols-3">
      {row("new_card", "New card", "A card just landed in the queue.")}
      {row(
        "regression",
        "Likely regression",
        "A recent push touched a suspected file.",
      )}
      {row(
        "approved",
        "Approved",
        "Someone approved the card and it became a GitHub issue / comment.",
      )}
    </div>
  );
}

function SlackDestinationRow({
  destination,
  onDelete,
}: {
  destination: SlackDestination;
  onDelete: (id: number) => void;
}) {
  const update = useUpdateSlackDestination();
  const test = useTestSlackDestination();
  const [testMsg, setTestMsg] = useState<string | null>(null);
  const [testOk, setTestOk] = useState<boolean | null>(null);

  const toggle = async (key: keyof SlackEvents) => {
    await update.mutateAsync({
      id: destination.id,
      body: {
        events: { ...destination.events, [key]: !destination.events[key] },
      },
    });
  };

  return (
    <li className="flex flex-col gap-3 py-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="font-medium">{destination.name}</div>
          <div className="text-xs text-muted-foreground">
            {destination.channel_hint
              ? `${destination.channel_hint} · `
              : ""}
            hook <span className="font-mono">{destination.webhook_hint}</span>
          </div>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={test.isPending}
            onClick={async () => {
              setTestMsg(null);
              setTestOk(null);
              try {
                const r = await test.mutateAsync(destination.id);
                setTestOk(r.ok);
                setTestMsg(
                  r.ok
                    ? "sent — check your Slack channel"
                    : `failed (${r.status_code ?? "network"}): ${r.detail ?? ""}`,
                );
              } catch (e) {
                setTestOk(false);
                setTestMsg(
                  e instanceof Error ? e.message : "test failed",
                );
              }
            }}
          >
            {test.isPending ? "testing…" : "Test"}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              if (
                confirm(
                  `Remove Slack destination "${destination.name}"? No more bugsift notifications will go to this webhook.`,
                )
              ) {
                onDelete(destination.id);
              }
            }}
          >
            <Trash2 className="mr-1.5 h-3.5 w-3.5" />
            Remove
          </Button>
        </div>
      </div>
      <div className="flex flex-wrap gap-4 text-xs">
        {(
          [
            ["new_card", "new card"],
            ["regression", "likely regression"],
            ["approved", "approved"],
          ] as [keyof SlackEvents, string][]
        ).map(([key, label]) => (
          <label key={key} className="inline-flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={destination.events[key]}
              onChange={() => toggle(key)}
              disabled={update.isPending}
            />
            <span>{label}</span>
          </label>
        ))}
      </div>
      {testMsg && (
        <p
          className={
            "rounded-md border px-3 py-1.5 text-xs " +
            (testOk
              ? "border-primary/30 bg-primary/5 text-primary"
              : "border-destructive/30 bg-destructive/5 text-destructive")
          }
        >
          {testMsg}
        </p>
      )}
    </li>
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
