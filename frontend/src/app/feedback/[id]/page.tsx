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
  type AnalysisChatMessage,
  type FeedbackApp,
  type FeedbackDigest,
  type RepoAnalysis,
  useAddCorrection,
  useAnalysis,
  useAnalysisChats,
  useAskAnalysis,
  useClearAnalysisChats,
  useComputeCurrentDigest,
  useFeedbackApp,
  useFeedbackDigests,
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

          <TrendsSection appId={app.data.id} />

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
          <ChatBlock appId={appId} />
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

function ChatBlock({ appId }: { appId: number }) {
  const chats = useAnalysisChats(appId, true);
  const ask = useAskAnalysis();
  const clear = useClearAnalysisChats();
  const [question, setQuestion] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    const q = question.trim();
    if (!q) return;
    try {
      await ask.mutateAsync({ appId, question: q });
      setQuestion("");
    } catch (e2) {
      if (e2 instanceof ApiError) setErr(e2.message);
      else if (e2 instanceof Error) setErr(e2.message);
      else setErr("question failed");
    }
  };

  const messages = chats.data ?? [];

  return (
    <section className="rounded-lg border bg-card p-6 shadow-sm">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <MessageSquare className="h-4 w-4 text-muted-foreground" />
          <h3 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">
            Ask this repo
          </h3>
        </div>
        {messages.length > 0 && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              if (confirm("Clear the Q&A history for this repo?")) {
                clear.mutate(appId);
              }
            }}
            disabled={clear.isPending}
          >
            Clear
          </Button>
        )}
      </div>
      <p className="mt-1 text-sm text-muted-foreground">
        Questions about the codebase. bugsift answers using the stored
        analysis + indexed code. Every concrete claim is grounded in a
        file:line citation; no speculation.
      </p>

      {chats.isLoading ? (
        <Skeleton className="mt-5 h-24 w-full" />
      ) : messages.length === 0 ? (
        <div className="mt-5 rounded-md border bg-background p-4 text-sm text-muted-foreground">
          No questions yet. Try <em>&ldquo;Where does auth happen?&rdquo;</em>{" "}
          or <em>&ldquo;What triggers the triage queue?&rdquo;</em>
        </div>
      ) : (
        <ul className="mt-5 space-y-3">
          {messages.map((m) => (
            <ChatTurn key={m.id} message={m} />
          ))}
        </ul>
      )}

      <form onSubmit={submit} className="mt-5 space-y-2">
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          className="min-h-[72px] w-full rounded-md border bg-background p-2 text-sm"
          placeholder="Ask something about this codebase…"
          disabled={ask.isPending}
        />
        <div className="flex items-center gap-2">
          <Button type="submit" size="sm" disabled={ask.isPending || !question.trim()}>
            {ask.isPending ? "thinking…" : "Ask"}
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

function ChatTurn({ message }: { message: AnalysisChatMessage }) {
  const isUser = message.role === "user";
  return (
    <li
      className={
        "rounded-md border p-3 text-sm " +
        (isUser ? "bg-muted/30" : "bg-background")
      }
    >
      <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
        {isUser ? "you" : "bugsift"}
      </div>
      <div className="mt-1 whitespace-pre-wrap leading-relaxed">
        {message.content}
      </div>
      {message.citations && message.citations.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5 text-xs">
          {message.citations.map((c, i) => (
            <code
              key={`${c.file_path}:${c.line_range}:${i}`}
              className="rounded border bg-muted/30 px-1.5 py-0.5"
            >
              {c.file_path}
              {c.line_range ? `:${c.line_range}` : ""}
            </code>
          ))}
        </div>
      )}
    </li>
  );
}

function TrendsSection({ appId }: { appId: number }) {
  const digests = useFeedbackDigests(appId, true);
  const compute = useComputeCurrentDigest();
  const [err, setErr] = useState<string | null>(null);
  const current: FeedbackDigest | null = digests.data?.[0] ?? null;

  return (
    <section className="mb-6 rounded-lg border bg-card p-6 shadow-sm">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-base font-medium">Trends this week</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            bugsift clusters similar feedback reports so you can see
            what&apos;s actually blowing up, not just the newest card.
            Refresh the digest any time — we recompute over the
            week&apos;s embeddings.
          </p>
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={async () => {
            setErr(null);
            try {
              await compute.mutateAsync(appId);
            } catch (e) {
              setErr(
                e instanceof ApiError
                  ? e.message
                  : e instanceof Error
                    ? e.message
                    : "failed to compute digest",
              );
            }
          }}
          disabled={compute.isPending}
        >
          <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
          {compute.isPending ? "computing…" : current ? "Refresh" : "Compute digest"}
        </Button>
      </div>
      {err && (
        <p className="mt-3 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-1.5 text-xs text-destructive">
          {err}
        </p>
      )}
      {digests.isLoading ? (
        <Skeleton className="mt-5 h-24 w-full" />
      ) : current ? (
        <DigestBody digest={current} />
      ) : (
        <p className="mt-5 text-sm text-muted-foreground">
          No digest yet. Click <em>Compute digest</em> to generate one.
        </p>
      )}
    </section>
  );
}

function DigestBody({ digest }: { digest: FeedbackDigest }) {
  const delta = digest.report_count - digest.previous_report_count;
  const pctLabel = _deltaLabel(digest.report_count, digest.previous_report_count);

  return (
    <div className="mt-5 space-y-5">
      <div className="flex flex-wrap items-baseline gap-4">
        <div>
          <div className="text-3xl font-semibold">{digest.report_count}</div>
          <div className="text-xs text-muted-foreground">
            reports · {_friendlyRange(digest.period_start, digest.period_end)}
          </div>
        </div>
        <div
          className={
            "rounded-full border px-2.5 py-1 text-xs font-medium " +
            (delta > 0
              ? "border-red-500/40 bg-red-500/10 text-red-700"
              : delta < 0
                ? "border-green-600/40 bg-green-600/10 text-green-700"
                : "border-border bg-muted/30 text-muted-foreground")
          }
        >
          {delta > 0 ? "▲" : delta < 0 ? "▼" : "·"} {Math.abs(delta)} vs last week
          {pctLabel ? ` (${pctLabel})` : ""}
        </div>
      </div>

      {Object.keys(digest.severity_breakdown).length > 0 && (
        <div>
          <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Severity
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {(
              ["blocker", "high", "medium", "low", "none"] as const
            ).flatMap((key) => {
              const n = digest.severity_breakdown[key];
              if (!n) return [];
              const cls = {
                blocker: "border-destructive/50 bg-destructive/10 text-destructive",
                high: "border-red-500/40 bg-red-500/10 text-red-700",
                medium: "border-amber-500/40 bg-amber-500/10 text-amber-700",
                low: "border-border bg-muted/30 text-muted-foreground",
                none: "border-border bg-muted/20 text-muted-foreground",
              }[key];
              return [
                <span
                  key={key}
                  className={`rounded-full border px-2 py-0.5 text-xs ${cls}`}
                >
                  {key} · {n}
                </span>,
              ];
            })}
          </div>
        </div>
      )}

      {digest.clusters.length > 0 && (
        <div>
          <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Top patterns
          </div>
          <ul className="mt-2 space-y-2">
            {digest.clusters.map((c, i) => (
              <li
                key={i}
                className="rounded-md border bg-background p-3 text-sm"
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span className="font-medium">×{c.size} reports</span>
                  {c.card_ids.length > 0 && (
                    <span className="text-xs text-muted-foreground">
                      {c.card_ids.length} card{c.card_ids.length === 1 ? "" : "s"}
                    </span>
                  )}
                </div>
                <p className="mt-1 leading-relaxed">{c.representative}</p>
              </li>
            ))}
          </ul>
        </div>
      )}

      {digest.top_files.length > 0 && (
        <div>
          <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Most-implicated files
          </div>
          <ul className="mt-2 space-y-1 text-xs">
            {digest.top_files.map((f) => (
              <li key={f.file_path}>
                <code className="rounded border bg-muted/30 px-1.5 py-0.5">
                  {f.file_path}
                </code>
                <span className="ml-2 text-muted-foreground">
                  {f.card_count} card{f.card_count === 1 ? "" : "s"}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="text-[10px] text-muted-foreground">
        last computed {new Date(digest.generated_at).toLocaleString()}
      </div>
    </div>
  );
}

function _deltaLabel(current: number, previous: number): string | null {
  if (previous === 0) return current > 0 ? "new" : null;
  const pct = Math.round(((current - previous) / previous) * 100);
  return `${pct >= 0 ? "+" : ""}${pct}%`;
}

function _friendlyRange(start: string, end: string): string {
  const s = new Date(start);
  const e = new Date(end);
  return `${s.toLocaleDateString()} – ${e.toLocaleDateString()}`;
}
