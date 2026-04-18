"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  type Card,
  useApproveCard,
  useEditCard,
  useSkipCard,
} from "@/lib/hooks";

export function TriageCard({ card }: { card: Card }) {
  const approve = useApproveCard();
  const skip = useSkipCard();
  const edit = useEditCard();
  const [draft, setDraft] = useState(card.draft_comment ?? "");
  const [isEditing, setIsEditing] = useState(false);

  const isPending = card.status === "pending";

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
              <Button
                size="sm"
                onClick={() => approve.mutate(card.id)}
                disabled={approve.isPending || !card.draft_comment}
              >
                {approve.isPending ? "posting…" : "Approve"}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => setIsEditing(true)}
                disabled={!card.draft_comment}
              >
                Edit
              </Button>
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
