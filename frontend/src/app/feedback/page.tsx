"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { ArrowRight, Check, Copy, MessageSquareWarning, Trash2 } from "lucide-react";

import { AppShell, EmptyState, PageHeader, Skeleton } from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api";
import {
  type FeedbackApp,
  useCreateFeedbackApp,
  useDeleteFeedbackApp,
  useFeedbackApps,
  useMe,
  useRepoBranches,
  useRepos,
  useTicketDestinations,
} from "@/lib/hooks";

export default function FeedbackAppsPage() {
  const me = useMe();
  const signedIn = Boolean(me.data);
  const apps = useFeedbackApps(signedIn);
  const repos = useRepos(signedIn);

  return (
    <AppShell me={me.data ?? null}>
      {!signedIn ? (
        <EmptyState
          icon={MessageSquareWarning}
          title="Sign in to manage feedback apps"
          description="Embed bugsift's widget in your product and route in-app bug reports through the same triage pipeline as GitHub issues."
        />
      ) : (
        <>
          <PageHeader
            title="Feedback apps"
            description="Register an app, embed the widget, and every bug report your users submit lands in the queue here (triage wiring ships in slice 2)."
          />
          <CreateForm repos={repos.data ?? []} />
          <div className="mt-8">
            <h2 className="mb-3 text-sm font-medium uppercase tracking-wide text-muted-foreground">
              Your apps
            </h2>
            {apps.isLoading ? (
              <Skeleton className="h-40 w-full" />
            ) : (apps.data ?? []).length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No feedback apps yet. Create one above to get a public key.
              </p>
            ) : (
              <ul className="space-y-4">
                {(apps.data ?? []).map((a) => (
                  <AppCard key={a.id} app={a} />
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </AppShell>
  );
}

function CreateForm({
  repos,
}: {
  repos: { id: number; full_name: string; default_branch: string }[];
}) {
  const create = useCreateFeedbackApp();
  const [name, setName] = useState("");
  const [repoId, setRepoId] = useState<string>("");
  const [branch, setBranch] = useState("");
  const [origins, setOrigins] = useState("");
  const [ticketDestId, setTicketDestId] = useState<string>("");
  const [err, setErr] = useState<string | null>(null);

  const selectedRepoNumId = repoId ? Number(repoId) : null;
  const branches = useRepoBranches(selectedRepoNumId, selectedRepoNumId !== null);
  const branchList = branches.data ?? [];
  const selectedRepo = repos.find((r) => r.id === selectedRepoNumId);
  const ticketDests = useTicketDestinations(true);

  return (
    <section className="rounded-lg border bg-card p-6 shadow-sm">
      <h2 className="text-base font-medium">Register a new app</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        Pick a descriptive name and the repo you want approved feedback to land
        in. You can leave the origin allowlist blank during development.
      </p>

      <form
        className="mt-5 grid gap-4 sm:grid-cols-2"
        onSubmit={async (e) => {
          e.preventDefault();
          setErr(null);
          if (!name.trim()) {
            setErr("give the app a name");
            return;
          }
          try {
            await create.mutateAsync({
              name: name.trim(),
              default_repo_id: repoId ? Number(repoId) : null,
              target_branch: branch.trim() || null,
              ticket_destination_id: ticketDestId ? Number(ticketDestId) : null,
              allowed_origins: origins
                .split(/[\s,]+/)
                .map((s) => s.trim())
                .filter(Boolean),
            });
            setName("");
            setRepoId("");
            setBranch("");
            setOrigins("");
            setTicketDestId("");
          } catch (e) {
            if (e instanceof ApiError) setErr(e.message);
            else if (e instanceof Error) setErr(e.message);
            else setErr("failed to create app");
          }
        }}
      >
        <div className="space-y-1">
          <Label htmlFor="name">Name</Label>
          <Input
            id="name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Acme Web"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="repo">Default repo (optional)</Label>
          <select
            id="repo"
            value={repoId}
            onChange={(e) => {
              setRepoId(e.target.value);
              // Reset the branch choice when the repo changes — the new
              // repo has its own branch list and the old value is likely
              // invalid.
              setBranch("");
            }}
            className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
          >
            <option value="">— choose a synced repo —</option>
            {repos.map((r) => (
              <option key={r.id} value={r.id}>
                {r.full_name}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="branch">Target branch (optional)</Label>
          <select
            id="branch"
            value={branch}
            onChange={(e) => setBranch(e.target.value)}
            disabled={!selectedRepoNumId || branches.isLoading}
            className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm disabled:opacity-60"
          >
            {!selectedRepoNumId ? (
              <option value="">— pick a repo first —</option>
            ) : branches.isLoading ? (
              <option value="">loading branches…</option>
            ) : branches.isError ? (
              <option value="">could not load branches</option>
            ) : branchList.length === 0 ? (
              <option value="">no branches returned</option>
            ) : (
              <>
                <option value="">
                  default ({selectedRepo?.default_branch ?? "main"})
                </option>
                {branchList.map((b) => (
                  <option key={b.name} value={b.name}>
                    {b.name}
                    {b.is_default ? " · default" : ""}
                  </option>
                ))}
              </>
            )}
          </select>
        </div>
        <div className="sm:col-span-2 space-y-1">
          <Label htmlFor="ticket-dest">Approved feedback goes to (optional)</Label>
          <select
            id="ticket-dest"
            value={ticketDestId}
            onChange={(e) => setTicketDestId(e.target.value)}
            className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
          >
            <option value="">GitHub Issues in the default repo (default)</option>
            {(ticketDests.data ?? []).map((d) => (
              <option key={d.id} value={d.id}>
                {d.provider}: {d.name} ({d.default_project_key})
              </option>
            ))}
          </select>
          <p className="text-xs text-muted-foreground">
            Manage ticket destinations on{" "}
            <Link href="/settings" className="underline underline-offset-4">
              Settings
            </Link>
            .
          </p>
        </div>

        <div className="sm:col-span-2 space-y-1">
          <Label htmlFor="origins">Allowed origins (optional, space or comma separated)</Label>
          <Input
            id="origins"
            value={origins}
            onChange={(e) => setOrigins(e.target.value)}
            placeholder="https://app.example.com https://staging.example.com"
          />
        </div>
        <div className="sm:col-span-2 flex items-center gap-3">
          <Button type="submit" disabled={create.isPending}>
            {create.isPending ? "creating…" : "Create app"}
          </Button>
          {err && (
            <span className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-1.5 text-xs text-destructive">
              {err}
            </span>
          )}
        </div>
      </form>
    </section>
  );
}

function AppCard({ app }: { app: FeedbackApp }) {
  const del = useDeleteFeedbackApp();
  const snippet = useMemo(
    () =>
      `<script src="${widgetBase()}/widget.js"\n        data-app-key="${app.public_key}" defer></script>`,
    [app.public_key],
  );

  return (
    <li className="rounded-lg border bg-card p-5 shadow-sm">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="truncate text-base font-medium">{app.name}</div>
          <div className="mt-1 text-xs text-muted-foreground">
            {app.ticket_destination_id && app.ticket_destination_name ? (
              <>
                approved feedback →{" "}
                <span className="font-mono">
                  {app.ticket_destination_provider}: {app.ticket_destination_name}
                </span>
              </>
            ) : app.default_repo_full_name ? (
              <>
                approved feedback →{" "}
                <span className="font-mono">{app.default_repo_full_name}</span>
                {" @ "}
                <span className="font-mono">
                  {app.target_branch ?? app.default_repo_branch ?? "main"}
                </span>
              </>
            ) : (
              <span>no default repo yet — approve will fail until you set one</span>
            )}
            {" · "}
            {app.report_count} report{app.report_count === 1 ? "" : "s"}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Link
            href={`/feedback/${app.id}`}
            className="inline-flex h-8 items-center gap-1.5 rounded-md border border-input bg-background px-3 text-xs font-medium hover:bg-accent hover:text-accent-foreground"
          >
            Analysis
            <ArrowRight className="h-3.5 w-3.5" />
          </Link>
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              if (confirm(`Remove feedback app "${app.name}"? Existing reports stay in the DB.`)) {
                del.mutate(app.id);
              }
            }}
            disabled={del.isPending}
          >
            <Trash2 className="mr-1.5 h-3.5 w-3.5" />
            Remove
          </Button>
        </div>
      </div>

      <div className="mt-4 space-y-3">
        <FieldRow label="Public key" value={app.public_key} mono />
        {app.allowed_origins && app.allowed_origins.length > 0 && (
          <FieldRow
            label="Allowed origins"
            value={app.allowed_origins.join("  ")}
          />
        )}
        <div>
          <div className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Embed snippet
          </div>
          <CodeBlock text={snippet} />
          <p className="mt-2 text-xs text-muted-foreground">
            Paste this before <code>&lt;/body&gt;</code>. The widget renders a
            floating <strong>🐛 Report</strong> button. Call{" "}
            <code>window.bugsift.identify(userId)</code> after login to attach a
            hashed reporter id to reports.
          </p>
        </div>
      </div>
    </li>
  );
}

function FieldRow({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  const [copied, setCopied] = useState(false);
  return (
    <div>
      <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="mt-1 flex items-center gap-2">
        <span
          className={
            "flex-1 rounded-md border bg-muted/30 px-2.5 py-1.5 " +
            (mono ? "font-mono text-xs break-all" : "text-sm")
          }
        >
          {value}
        </span>
        <button
          type="button"
          className="rounded-md border px-2 py-1 text-xs hover:bg-accent"
          onClick={async () => {
            await navigator.clipboard.writeText(value);
            setCopied(true);
            setTimeout(() => setCopied(false), 1200);
          }}
        >
          {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
        </button>
      </div>
    </div>
  );
}

function CodeBlock({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="relative">
      <pre className="max-h-40 overflow-auto rounded-md border bg-background p-3 font-mono text-xs leading-relaxed">
        {text}
      </pre>
      <button
        type="button"
        className="absolute right-2 top-2 rounded-md border bg-card px-2 py-1 text-xs hover:bg-accent"
        onClick={async () => {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1200);
        }}
      >
        {copied ? (
          <Check className="h-3.5 w-3.5" />
        ) : (
          <Copy className="h-3.5 w-3.5" />
        )}
      </button>
    </div>
  );
}

function widgetBase(): string {
  if (typeof window === "undefined") return "";
  // The widget script is served from the same origin as the dashboard in
  // dev / self-hosted setups. If/when we move it to a CDN, swap the base
  // from a config value here.
  return window.location.origin + "/api";
}
