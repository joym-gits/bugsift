"use client";

import { useState } from "react";
import { Activity, Copy } from "lucide-react";

import { AppShell, EmptyState, PageHeader, Skeleton } from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import {
  useCreateMonitorToken,
  useMe,
  useMonitoringEvents,
  useRepos,
} from "@/lib/hooks";

export default function MonitoringPage() {
  const me = useMe();
  const signedIn = Boolean(me.data);
  const repos = useRepos(signedIn);
  const [repoId, setRepoId] = useState<number | null>(null);
  const selectedRepo = repoId ?? repos.data?.[0]?.id ?? null;
  const events = useMonitoringEvents(selectedRepo, signedIn);
  const createToken = useCreateMonitorToken();
  const [newToken, setNewToken] = useState<string | null>(null);
  const [tokenError, setTokenError] = useState<string | null>(null);

  return (
    <AppShell me={me.data ?? null}>
      {!signedIn ? (
        <EmptyState
          icon={Activity}
          title="Sign in to see monitoring"
          description="Production/runtime errors ingested from Sentry, Datadog, or a custom sender, correlated against triage cards by file path."
        />
      ) : (
        <>
          <PageHeader
            title="Monitoring"
            description="Errors ingested from an external monitoring provider, correlated against existing findings by file path."
          />

          <section className="mb-6 flex flex-wrap items-end gap-3 rounded-lg border bg-card p-4 shadow-elev-1">
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground" htmlFor="repo">
                Repo
              </label>
              <select
                id="repo"
                value={selectedRepo ?? ""}
                onChange={(e) => setRepoId(e.target.value ? Number(e.target.value) : null)}
                className="flex h-10 w-64 rounded-md border border-input bg-background px-3 py-2 text-sm"
              >
                {(repos.data ?? []).map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.full_name}
                  </option>
                ))}
              </select>
            </div>
            <Button
              variant="outline"
              disabled={selectedRepo === null || createToken.isPending}
              onClick={async () => {
                if (selectedRepo === null) return;
                setTokenError(null);
                try {
                  const tok = await createToken.mutateAsync(selectedRepo);
                  setNewToken(tok.token);
                } catch (err) {
                  setTokenError(
                    err instanceof ApiError || err instanceof Error
                      ? err.message
                      : "failed to create token",
                  );
                }
              }}
            >
              {createToken.isPending ? "generating…" : "Generate ingest token"}
            </Button>
            <span className="text-xs text-muted-foreground">
              {events.data?.length ?? 0} event{events.data?.length === 1 ? "" : "s"}
            </span>
          </section>

          {newToken && (
            <section className="mb-6 rounded-lg border border-warning/40 bg-warning/5 p-4 text-sm shadow-elev-1">
              <p className="mb-2 font-medium">
                Shown once — copy it now. Send it as{" "}
                <code className="rounded bg-muted px-1 py-0.5 text-xs">
                  X-Bugsift-Monitor-Token
                </code>{" "}
                on <code className="rounded bg-muted px-1 py-0.5 text-xs">POST /monitoring/ingest</code>.
              </p>
              <div className="flex items-center gap-2">
                <code className="flex-1 truncate rounded-md border bg-background px-3 py-2 font-mono text-xs">
                  {newToken}
                </code>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => navigator.clipboard.writeText(newToken)}
                >
                  <Copy className="h-3.5 w-3.5" />
                </Button>
              </div>
            </section>
          )}
          {tokenError && (
            <p className="mb-6 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
              {tokenError}
            </p>
          )}

          <section className="rounded-lg border bg-card p-6 shadow-elev-1">
            {events.isLoading ? (
              <Skeleton className="h-24 w-full" />
            ) : events.data && events.data.length > 0 ? (
              <ul className="divide-y">
                {events.data.map((e) => (
                  <li key={e.id} className="flex items-start justify-between gap-4 py-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 text-xs text-muted-foreground">
                        <span className="rounded-full border px-2 py-0.5 uppercase">
                          {e.provider}
                        </span>
                        {e.level && <span>{e.level}</span>}
                        <span>· ×{e.occurrence_count}</span>
                      </div>
                      <p className="mt-1 truncate text-sm">{e.message}</p>
                      {e.file_paths && e.file_paths.length > 0 && (
                        <p className="mt-1 truncate font-mono text-xs text-muted-foreground">
                          {e.file_paths.join(", ")}
                        </p>
                      )}
                    </div>
                    <div className="shrink-0 text-right text-xs text-muted-foreground">
                      <div>{new Date(e.created_at).toLocaleString()}</div>
                      {e.correlated_card_id && (
                        <span className="mt-1 inline-block rounded-full border border-info/40 bg-info/10 px-2 py-0.5 text-info">
                          card #{e.correlated_card_id}
                        </span>
                      )}
                      {e.resolved_at ? (
                        <span className="mt-1 inline-block rounded-full border border-success/40 bg-success/10 px-2 py-0.5 text-success">
                          {e.resolution_status ?? "resolved"}
                        </span>
                      ) : e.correlated_card_id ? (
                        <span className="mt-1 inline-block rounded-full border border-warning/40 bg-warning/10 px-2 py-0.5 text-warning">
                          open
                        </span>
                      ) : null}
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">
                No monitoring events yet. Generate a token above and point your provider&apos;s
                outbound webhook at <code className="rounded bg-muted px-1 py-0.5">POST /monitoring/ingest</code>.
              </p>
            )}
          </section>
        </>
      )}
    </AppShell>
  );
}
