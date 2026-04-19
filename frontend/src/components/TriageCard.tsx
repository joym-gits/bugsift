"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import {
  type Card,
  useApproveCard,
  useCardFeedbackReports,
  useEditCard,
  useRerunCard,
  useSkipCard,
} from "@/lib/hooks";

function errMessage(e: unknown, fallback: string): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return fallback;
}

export function TriageCard({ card }: { card: Card }) {
  const approve = useApproveCard();
  const skip = useSkipCard();
  const edit = useEditCard();
  const rerun = useRerunCard();
  const [draft, setDraft] = useState(card.draft_comment ?? "");
  const [isEditing, setIsEditing] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionOk, setActionOk] = useState<string | null>(null);
  const [adminNote, setAdminNote] = useState("");

  const isPending = card.status === "pending";
  // Card never got classified (e.g. no LLM key at ingest time) — show
  // Retry as the primary action instead of Approve.
  const isStuck = isPending && !card.classification;

  return (
    <article className="rounded-md border bg-card p-4 shadow-sm">
      <header className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium">
            {card.repo_full_name}{" "}
            <span className="text-muted-foreground">
              {card.source === "feedback"
                ? card.github_issue_number
                  ? `#${card.github_issue_number}`
                  : `report${(card.feedback_report_count ?? 1) > 1 ? `s ×${card.feedback_report_count}` : ""}`
                : card.issue_number !== null
                  ? `#${card.issue_number}`
                  : ""}
            </span>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
            <span
              className={
                "rounded-full border px-2 py-0.5 " +
                (card.source === "feedback"
                  ? "border-blue-500/40 bg-blue-500/10 text-blue-700"
                  : "")
              }
            >
              {card.source === "feedback" ? "in-app feedback" : "github"}
            </span>
            <span className="rounded-full border px-2 py-0.5">
              {card.classification ?? "unclassified"}
            </span>
            {typeof card.confidence === "number" && (
              <span>· conf {card.confidence.toFixed(2)}</span>
            )}
            <span>· {card.status}</span>
            {card.proposed_action && <span>· {card.proposed_action}</span>}
          </div>
        </div>
        <time className="shrink-0 text-xs text-muted-foreground">
          {new Date(card.created_at).toLocaleString()}
        </time>
      </header>

      {card.github_issue_url && (
        <a
          href={card.github_issue_url}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-2 inline-flex items-center text-xs text-primary underline underline-offset-4"
        >
          View on GitHub ↗
        </a>
      )}

      {card.source === "feedback" && <FeedbackReports cardId={card.id} />}

      {card.budget_limited && (
        <div className="mt-2 inline-flex items-center gap-1 rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium text-amber-700">
          budget exhausted · expensive steps skipped
        </div>
      )}

      {card.rationale && (
        <p className="mt-3 text-xs text-muted-foreground">{card.rationale}</p>
      )}

      {(card.draft_comment || card.final_comment) && (
        <div className="mt-3">
          {isEditing && isPending ? (
            <textarea
              className="min-h-[120px] w-full rounded-md border bg-background p-3 text-sm"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
            />
          ) : (
            <pre className="whitespace-pre-wrap rounded-md border bg-muted/30 p-3 text-sm">
              {card.final_comment ?? card.draft_comment}
            </pre>
          )}
        </div>
      )}

      {card.proposed_labels && card.proposed_labels.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1 text-xs">
          {card.proposed_labels.map((lbl) => (
            <span key={lbl} className="rounded-full border px-2 py-0.5">
              {lbl}
            </span>
          ))}
        </div>
      )}

      {card.suspected_files && card.suspected_files.length > 0 && (
        <details className="mt-3 rounded-md border bg-muted/10 p-3 text-sm" open>
          <summary className="cursor-pointer text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Suspected files ({card.suspected_files.length})
          </summary>
          <ul className="mt-2 space-y-2">
            {card.suspected_files.map((f, i) => (
              <li key={`${f.file_path}-${i}`} className="flex flex-col gap-0.5">
                <div className="flex items-baseline justify-between gap-3">
                  <code className="truncate text-xs font-mono">
                    {f.file_path}:{f.line_range}
                  </code>
                  {githubBlobUrl(card, f) && (
                    <a
                      href={githubBlobUrl(card, f) ?? undefined}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="shrink-0 text-xs underline underline-offset-4"
                    >
                      view on GitHub
                    </a>
                  )}
                </div>
                <p className="text-xs text-muted-foreground">{f.rationale}</p>
              </li>
            ))}
          </ul>
        </details>
      )}

      {card.reproduction_verdict && (
        <details className="mt-3 rounded-md border bg-muted/10 p-3 text-sm">
          <summary className="flex cursor-pointer items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            <span>Reproduction</span>
            <span className={verdictBadgeClass(card.reproduction_verdict)}>
              {card.reproduction_verdict.replace(/_/g, " ")}
            </span>
          </summary>
          {card.reproduction_log && (
            <pre className="mt-2 max-h-[280px] overflow-auto whitespace-pre-wrap rounded bg-background p-2 font-mono text-xs">
              {card.reproduction_log}
            </pre>
          )}
        </details>
      )}

      {card.regression_suspects && card.regression_suspects.length > 0 && (
        <div className="mt-3 rounded-md border border-amber-500/40 bg-amber-500/5 p-3 text-sm">
          <div className="text-xs font-medium uppercase tracking-wide text-amber-700">
            Possible cause — recent pushes that touched suspected files
          </div>
          <ul className="mt-2 space-y-2">
            {card.regression_suspects.map((s) => (
              <li key={s.commit_sha} className="text-xs">
                <div className="flex flex-wrap items-baseline gap-2">
                  <a
                    href={`https://github.com/${card.repo_full_name}/commit/${s.commit_sha}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="font-mono underline underline-offset-4"
                  >
                    {s.short_sha}
                  </a>
                  <span className="font-medium">
                    {s.message_first_line || "(no message)"}
                  </span>
                  {s.pr_number !== null && s.pr_number !== undefined && (
                    <a
                      href={`https://github.com/${card.repo_full_name}/pull/${s.pr_number}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-700 underline underline-offset-4"
                    >
                      PR #{s.pr_number}
                    </a>
                  )}
                </div>
                <div className="mt-0.5 text-muted-foreground">
                  {(s.author_login || s.author_name || "someone")} ·{" "}
                  {new Date(s.pushed_at_iso).toLocaleString()}
                </div>
                <div className="mt-1 flex flex-wrap gap-1">
                  {s.overlapping_paths.map((p) => (
                    <code
                      key={p}
                      className="rounded border bg-background px-1.5 py-0.5 text-[10px]"
                    >
                      {p}
                    </code>
                  ))}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {card.duplicates && card.duplicates.length > 0 && (
        <div className="mt-3 rounded-md border bg-muted/10 p-3 text-sm">
          <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Likely duplicates
          </div>
          <ul className="mt-2 space-y-1">
            {card.duplicates.map((d) => (
              <li key={d.issue_number} className="text-xs">
                <a
                  href={`https://github.com/${card.repo_full_name}/issues/${d.issue_number}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-mono underline underline-offset-4"
                >
                  #{d.issue_number}
                </a>{" "}
                <span className="text-muted-foreground">
                  · conf {d.confidence.toFixed(2)} · {d.rationale}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {isPending && card.source === "feedback" && !isEditing && (
        <div className="mt-4">
          <label
            htmlFor={`admin-note-${card.id}`}
            className="text-xs font-medium uppercase tracking-wide text-muted-foreground"
          >
            Admin notes (optional — included in the GitHub issue)
          </label>
          <textarea
            id={`admin-note-${card.id}`}
            className="mt-1 min-h-[72px] w-full rounded-md border bg-background p-2 text-sm"
            value={adminNote}
            onChange={(e) => setAdminNote(e.target.value)}
            placeholder="e.g. probably the auth middleware — check session handling in app/middleware.py"
          />
        </div>
      )}

      {isPending && (
        <div className="mt-4 space-y-2">
          <div className="flex flex-wrap gap-2">
            {!isEditing ? (
              <>
                {isStuck ? (
                  <Button
                    size="sm"
                    onClick={async () => {
                      setActionError(null);
                      setActionOk(null);
                      try {
                        await rerun.mutateAsync(card.id);
                        setActionOk("Re-queued for triage.");
                      } catch (e) {
                        setActionError(errMessage(e, "rerun failed"));
                      }
                    }}
                    disabled={rerun.isPending}
                  >
                    {rerun.isPending ? "re-running…" : "Retry triage"}
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    onClick={async () => {
                      setActionError(null);
                      setActionOk(null);
                      try {
                        const result = await approve.mutateAsync({
                          id: card.id,
                          admin_note:
                            card.source === "feedback" ? adminNote : undefined,
                        });
                        if (card.source === "feedback") {
                          const url =
                            result?.github_issue_url ??
                            (result?.github_issue_number
                              ? `https://github.com/${card.repo_full_name}/issues/${result.github_issue_number}`
                              : null);
                          setActionOk(
                            url
                              ? `Opened GitHub issue #${result.github_issue_number ?? ""}: ${url}`
                              : "Opened GitHub issue.",
                          );
                          setAdminNote("");
                        } else {
                          setActionOk("Posted to GitHub.");
                        }
                      } catch (e) {
                        setActionError(errMessage(e, "approve failed"));
                      }
                    }}
                    disabled={
                      approve.isPending ||
                      (card.source !== "feedback" && !card.draft_comment)
                    }
                  >
                    {approve.isPending
                      ? card.source === "feedback"
                        ? "opening…"
                        : "posting…"
                      : card.source === "feedback"
                        ? "Open GitHub issue"
                        : "Approve"}
                  </Button>
                )}
                {!isStuck && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      setActionError(null);
                      setActionOk(null);
                      setIsEditing(true);
                    }}
                    disabled={!card.draft_comment}
                  >
                    Edit
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="outline"
                  onClick={async () => {
                    setActionError(null);
                    setActionOk(null);
                    try {
                      await skip.mutateAsync(card.id);
                      setActionOk("Skipped.");
                    } catch (e) {
                      setActionError(errMessage(e, "skip failed"));
                    }
                  }}
                  disabled={skip.isPending}
                >
                  Skip
                </Button>
              </>
            ) : (
              <>
                <Button
                  size="sm"
                  onClick={async () => {
                    setActionError(null);
                    setActionOk(null);
                    try {
                      await edit.mutateAsync({ id: card.id, draft_comment: draft });
                      setIsEditing(false);
                      setActionOk("Draft saved.");
                    } catch (e) {
                      setActionError(errMessage(e, "save failed"));
                    }
                  }}
                  disabled={edit.isPending || draft.trim() === (card.draft_comment ?? "").trim()}
                >
                  {edit.isPending ? "saving…" : "Save"}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    setDraft(card.draft_comment ?? "");
                    setIsEditing(false);
                  }}
                >
                  Cancel
                </Button>
              </>
            )}
          </div>
          {actionError && (
            <p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-1.5 text-xs text-destructive">
              {actionError}
            </p>
          )}
          {actionOk && !actionError && (
            <p className="rounded-md border border-primary/30 bg-primary/5 px-3 py-1.5 text-xs text-primary">
              {actionOk}
            </p>
          )}
        </div>
      )}
    </article>
  );
}

function FeedbackReports({ cardId }: { cardId: number }) {
  const reports = useCardFeedbackReports(cardId, true);
  if (reports.isLoading) return null;
  const items = reports.data ?? [];
  if (items.length === 0) return null;
  return (
    <details className="mt-3 rounded-md border bg-muted/10 p-3 text-sm" open>
      <summary className="cursor-pointer text-xs font-medium uppercase tracking-wide text-muted-foreground">
        User reports ({items.length})
      </summary>
      <ul className="mt-2 space-y-3">
        {items.map((r) => (
          <li key={r.id} className="rounded-md border bg-background p-3">
            <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
              <span className="truncate">
                {r.url ?? "unknown url"}
                {r.app_version && <span> · v{r.app_version}</span>}
              </span>
              <time className="shrink-0">
                {new Date(r.created_at).toLocaleString()}
              </time>
            </div>
            <pre className="mt-2 whitespace-pre-wrap text-sm">{r.body_text}</pre>
            {r.console_log && (
              <details className="mt-2">
                <summary className="cursor-pointer text-xs text-muted-foreground">
                  Console log
                </summary>
                <pre className="mt-1 max-h-40 overflow-auto rounded bg-muted/40 p-2 font-mono text-[11px]">
                  {r.console_log}
                </pre>
              </details>
            )}
          </li>
        ))}
      </ul>
    </details>
  );
}

function verdictBadgeClass(verdict: string): string {
  const base = "rounded-full border px-2 py-0.5 text-[10px] normal-case";
  switch (verdict) {
    case "reproduced":
      return `${base} border-destructive/40 bg-destructive/10 text-destructive`;
    case "not_reproduced":
      return `${base} border-green-600/40 bg-green-600/10 text-green-700`;
    default:
      return `${base}`;
  }
}

function githubBlobUrl(
  card: Card,
  file: { file_path: string; line_range: string },
): string | null {
  if (!card.repo_full_name) return null;
  const branch = card.repo_default_branch || "HEAD";
  const path = encodeURI(file.file_path);
  const [start, end] = file.line_range.split("-").map((s) => s.trim());
  const anchor =
    start && end && start !== end
      ? `#L${start}-L${end}`
      : start
        ? `#L${start}`
        : "";
  return `https://github.com/${card.repo_full_name}/blob/${branch}/${path}${anchor}`;
}
