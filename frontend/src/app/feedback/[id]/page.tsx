"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import {
  ArrowLeft,
  BookOpen,
  MessageSquare,
  RefreshCw,
  Sparkles,
} from "lucide-react";

import { AppShell, EmptyState, PageHeader, Skeleton } from "@/components/AppShell";
import { Mermaid } from "@/components/Mermaid";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import {
  type FeedbackApp,
  type RepoAnalysis,
  useAddCorrection,
  useAnalysis,
  useFeedbackApp,
  useKickAnalysis,
  useMe,
} from "@/lib/hooks";

export default function FeedbackAppDetailPage() {
  const params = useParams<{ id: string }>();
  const appId = params?.id ? Number(params.id) : null;
  const me = useMe();
  const signedIn = Boolean(me.data);
  const app = useFeedbackApp(appId, signedIn);

  // While the status is pending/running, poll hard so progress is visible;
  // otherwise just refetch on navigation.
  const analysis = useAnalysis(
    appId,
    signedIn,
    analysisShouldPoll(app.data) ? 3000 : false,
  );

  return (
    <AppShell me={me.data ?? null}>
      {!signedIn ? (
        <EmptyState
          icon={BookOpen}
          title="Sign in to view a feedback app's analysis"
          description="Analyses are private — they can expose file paths and code structure from your repo."
        />
      ) : app.isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : !app.data ? (
        <EmptyState
          icon={BookOpen}
          title="Feedback app not found"
          description="It may have been removed, or it's owned by a different user."
          action={
            <Link
              href="/feedback"
              className="inline-flex h-10 items-center gap-1 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90"
            >
              Back to feedback apps
            </Link>
          }
        />
      ) : (
        <>
          <div className="mb-2">
            <Link
              href="/feedback"
              className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
            >
              <ArrowLeft className="h-3 w-3" /> feedback apps
            </Link>
          </div>
          <PageHeader
            title={app.data.name}
            description={summaryLine(app.data)}
          />

          <AnalysisSection
            appId={app.data.id}
            app={app.data}
            analysis={analysis.data ?? null}
            loading={analysis.isLoading}
          />
        </>
      )}
    </AppShell>
  );
}

function analysisShouldPoll(app: FeedbackApp | null | undefined): boolean {
  if (!app) return false;
  return true; // detail page always polls; the hook only fires when appId resolves
}

function summaryLine(app: FeedbackApp): string {
  const repo = app.default_repo_full_name ?? "(no repo linked)";
  const branch = app.target_branch ?? app.default_repo_branch ?? "main";
  return `${repo} @ ${branch} · bugsift's analysis is shared across any feedback app pointing at this branch.`;
}

function AnalysisSection({
  appId,
  app,
  analysis,
  loading,
}: {
  appId: number;
  app: FeedbackApp;
  analysis: RepoAnalysis | null;
  loading: boolean;
}) {
  const kick = useKickAnalysis();
  const addCorrection = useAddCorrection();
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState("");

  const running =
    analysis?.status === "pending" || analysis?.status === "running";
  const canRegenerate = !running;

  return (
    <div className="space-y-6">
      <section className="rounded-lg border bg-card p-6 shadow-sm">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-primary" />
              <h2 className="text-base font-medium">Repo analysis</h2>
              {analysis && <StatusPill status={analysis.status} />}
            </div>
            <p className="mt-1 text-sm text-muted-foreground">
              bugsift reads the indexed code and produces a hierarchical
              summary you can interact with. Corrections below feed back
              into the next regeneration so the LLM respects what you
              know.
            </p>
          </div>
          <Button
            onClick={async () => {
              setErr(null);
              try {
                await kick.mutateAsync(appId);
              } catch (e) {
                setErr(
                  e instanceof ApiError
                    ? e.message
                    : e instanceof Error
                      ? e.message
                      : "analyze failed",
                );
              }
            }}
            disabled={kick.isPending || running}
          >
            <RefreshCw className="mr-2 h-4 w-4" />
            {kick.isPending || running
              ? "analyzing…"
              : analysis
                ? "Re-analyze"
                : "Analyze"}
          </Button>
        </div>
        {err && (
          <p className="mt-3 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-1.5 text-xs text-destructive">
            {err}
          </p>
        )}
        {analysis?.error_detail && (
          <p className="mt-3 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
            {analysis.error_detail}
          </p>
        )}
        {analysis?.generated_at && (
          <p className="mt-3 text-xs text-muted-foreground">
            generated {new Date(analysis.generated_at).toLocaleString()}
          </p>
        )}
      </section>

      {loading && !analysis && <Skeleton className="h-64 w-full" />}

      {analysis?.status === "ready" && analysis.structured_json && (
        <>
          <SummaryBlock analysis={analysis} />
          <DiagramBlock analysis={analysis} />
          <ComponentsBlock analysis={analysis} />
          <FlowsBlock analysis={analysis} />
          <EntryPointsBlock analysis={analysis} />
          <OverridesBlock
            analysis={analysis}
            note={note}
            setNote={setNote}
            onSubmit={async () => {
              if (!note.trim()) return;
              try {
                await addCorrection.mutateAsync({ appId, note: note.trim() });
                setNote("");
              } catch (e) {
                setErr(
                  e instanceof ApiError
                    ? e.message
                    : e instanceof Error
                      ? e.message
                      : "failed to save correction",
                );
              }
            }}
            pending={addCorrection.isPending}
            canRegenerate={canRegenerate}
            onRegenerate={async () => {
              try {
                await kick.mutateAsync(appId);
              } catch (e) {
                setErr(
                  e instanceof ApiError
                    ? e.message
                    : e instanceof Error
                      ? e.message
                      : "analyze failed",
                );
              }
            }}
          />
        </>
      )}

      {analysis?.status === "pending" && (
        <p className="rounded-md border border-primary/30 bg-primary/5 px-3 py-2 text-sm text-primary">
          Queued. This page polls for progress — you can leave it open.
        </p>
      )}
      {analysis?.status === "running" && (
        <p className="rounded-md border border-primary/30 bg-primary/5 px-3 py-2 text-sm text-primary">
          Analysis in progress. First runs on a real repo take a minute or two.
        </p>
      )}
      {!loading && !analysis && (
        <EmptyState
          icon={Sparkles}
          title="No analysis yet"
          description={`Click Analyze to generate a hierarchical summary of ${app.default_repo_full_name ?? "the linked repo"}. Uses the indexed code, so make sure indexing is 'ready' first.`}
        />
      )}
    </div>
  );
}

function StatusPill({ status }: { status: RepoAnalysis["status"] }) {
  const map: Record<RepoAnalysis["status"], string> = {
    pending: "border-amber-500/40 bg-amber-500/10 text-amber-700",
    running: "border-primary/40 bg-primary/10 text-primary",
    ready: "border-green-600/40 bg-green-600/10 text-green-700",
    failed: "border-destructive/40 bg-destructive/10 text-destructive",
  };
  return (
    <span
      className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${map[status]}`}
    >
      {status}
    </span>
  );
}

function SummaryBlock({ analysis }: { analysis: RepoAnalysis }) {
  const s = analysis.structured_json?.summary;
  if (!s) return null;
  return (
    <section className="rounded-lg border bg-card p-6 shadow-sm">
      <h3 className="mb-2 text-sm font-medium uppercase tracking-wide text-muted-foreground">
        Summary
      </h3>
      <p className="text-sm leading-relaxed">{s}</p>
    </section>
  );
}

function DiagramBlock({ analysis }: { analysis: RepoAnalysis }) {
  const src =
    analysis.mermaid_src ||
    analysis.structured_json?.mermaid_overview ||
    "";
  if (!src.trim()) return null;
  return (
    <section className="rounded-lg border bg-card p-6 shadow-sm">
      <h3 className="mb-3 text-sm font-medium uppercase tracking-wide text-muted-foreground">
        Architecture diagram
      </h3>
      <Mermaid source={src} />
    </section>
  );
}

function ComponentsBlock({ analysis }: { analysis: RepoAnalysis }) {
  const components = analysis.structured_json?.components ?? [];
  if (components.length === 0) return null;
  return (
    <section className="rounded-lg border bg-card p-6 shadow-sm">
      <h3 className="mb-3 text-sm font-medium uppercase tracking-wide text-muted-foreground">
        Components
      </h3>
      <ul className="space-y-4">
        {components.map((c) => (
          <li key={c.path + c.name} className="rounded-md border bg-background p-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <div className="font-medium">{c.name}</div>
              <code className="text-xs text-muted-foreground">{c.path}</code>
            </div>
            <p className="mt-2 text-sm leading-relaxed">{c.role}</p>
            {c.citations && c.citations.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1 text-xs">
                {c.citations.map((cit) => (
                  <code
                    key={cit}
                    className="rounded border bg-muted/30 px-1.5 py-0.5"
                  >
                    {cit}
                  </code>
                ))}
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function FlowsBlock({ analysis }: { analysis: RepoAnalysis }) {
  const flows = analysis.structured_json?.flows ?? [];
  if (flows.length === 0) return null;
  return (
    <section className="rounded-lg border bg-card p-6 shadow-sm">
      <h3 className="mb-3 text-sm font-medium uppercase tracking-wide text-muted-foreground">
        Flows
      </h3>
      <div className="space-y-5">
        {flows.map((f) => (
          <div key={f.name} className="rounded-md border bg-background p-4">
            <div className="text-sm font-medium">{f.name}</div>
            <p className="mt-1 text-sm leading-relaxed">{f.description}</p>
            {f.mermaid && (
              <div className="mt-3">
                <Mermaid source={f.mermaid} />
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

function EntryPointsBlock({ analysis }: { analysis: RepoAnalysis }) {
  const entries = analysis.structured_json?.entry_points ?? [];
  const deps = analysis.structured_json?.dependencies ?? [];
  if (entries.length === 0 && deps.length === 0) return null;
  return (
    <section className="rounded-lg border bg-card p-6 shadow-sm">
      {entries.length > 0 && (
        <>
          <h3 className="mb-3 text-sm font-medium uppercase tracking-wide text-muted-foreground">
            Entry points
          </h3>
          <ul className="mb-5 space-y-1 text-sm">
            {entries.map((e) => (
              <li key={e.file + e.name}>
                <span className="font-medium">{e.name}</span>
                <code className="ml-2 text-xs text-muted-foreground">{e.file}</code>
                {e.note && (
                  <span className="ml-2 text-xs text-muted-foreground">
                    — {e.note}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
      {deps.length > 0 && (
        <>
          <h3 className="mb-3 text-sm font-medium uppercase tracking-wide text-muted-foreground">
            Dependencies
          </h3>
          <div className="flex flex-wrap gap-1.5 text-xs">
            {deps.map((d) => (
              <code key={d} className="rounded border bg-muted/30 px-2 py-0.5">
                {d}
              </code>
            ))}
          </div>
        </>
      )}
    </section>
  );
}

function OverridesBlock({
  analysis,
  note,
  setNote,
  onSubmit,
  pending,
  canRegenerate,
  onRegenerate,
}: {
  analysis: RepoAnalysis;
  note: string;
  setNote: (v: string) => void;
  onSubmit: () => void;
  pending: boolean;
  canRegenerate: boolean;
  onRegenerate: () => void;
}) {
  return (
    <section className="rounded-lg border bg-card p-6 shadow-sm">
      <div className="flex items-center gap-2">
        <MessageSquare className="h-4 w-4 text-muted-foreground" />
        <h3 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">
          Corrections ({analysis.overrides.length})
        </h3>
      </div>
      <p className="mt-1 text-sm text-muted-foreground">
        Tell bugsift what it got wrong. Saved corrections get injected into the
        synthesis prompt on the next regeneration.
      </p>

      {analysis.overrides.length > 0 && (
        <ul className="mt-4 space-y-2">
          {analysis.overrides.map((o, i) => (
            <li
              key={i}
              className="rounded-md border bg-background px-3 py-2 text-sm"
            >
              {o}
            </li>
          ))}
        </ul>
      )}

      <div className="mt-4 space-y-2">
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          className="min-h-[72px] w-full rounded-md border bg-background p-2 text-sm"
          placeholder="e.g. The queue backend is Kafka, not Redis. The 'Backend' component also includes the worker subtree."
        />
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            onClick={onSubmit}
            disabled={pending || !note.trim()}
          >
            {pending ? "saving…" : "Save correction"}
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={onRegenerate}
            disabled={!canRegenerate || analysis.overrides.length === 0}
            title={
              analysis.overrides.length === 0
                ? "Save at least one correction first"
                : undefined
            }
          >
            Re-analyze with corrections
          </Button>
        </div>
      </div>
    </section>
  );
}
