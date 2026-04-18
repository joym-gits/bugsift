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
