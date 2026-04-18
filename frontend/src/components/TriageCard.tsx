"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  type Card,
  useApproveCard,
  useEditCard,
  useRerunCard,
  useSkipCard,
} from "@/lib/hooks";

export function TriageCard({ card }: { card: Card }) {
  const approve = useApproveCard();
  const skip = useSkipCard();
  const edit = useEditCard();
  const rerun = useRerunCard();
  const [draft, setDraft] = useState(card.draft_comment ?? "");
  const [isEditing, setIsEditing] = useState(false);

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
            <span className="text-muted-foreground">#{card.issue_number}</span>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
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

      {isPending && (
        <div className="mt-4 flex flex-wrap gap-2">
          {!isEditing ? (
            <>
              {isStuck ? (
                <Button
                  size="sm"
                  onClick={() => rerun.mutate(card.id)}
                  disabled={rerun.isPending}
                >
                  {rerun.isPending ? "re-running…" : "Retry triage"}
                </Button>
              ) : (
                <Button
                  size="sm"
                  onClick={() => approve.mutate(card.id)}
                  disabled={approve.isPending || !card.draft_comment}
                >
                  {approve.isPending ? "posting…" : "Approve"}
                </Button>
              )}
              {!isStuck && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setIsEditing(true)}
                  disabled={!card.draft_comment}
                >
                  Edit
                </Button>
              )}
              <Button
                size="sm"
                variant="outline"
                onClick={() => skip.mutate(card.id)}
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
                  await edit.mutateAsync({ id: card.id, draft_comment: draft });
                  setIsEditing(false);
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
      )}
    </article>
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
