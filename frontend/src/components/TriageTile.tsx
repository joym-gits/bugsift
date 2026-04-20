"use client";

import {
  Clock,
  GitPullRequestArrow,
  MessageSquareWarning,
  ShieldCheck,
  Sparkles,
  UserRound,
} from "lucide-react";

import { SeverityPill } from "@/components/TriageCard";
import { type Card } from "@/lib/hooks";
import { cn } from "@/lib/utils";

export function TriageTile({
  card,
  active,
  onOpen,
}: {
  card: Card;
  active: boolean;
  onOpen: () => void;
}) {
  const issueLabel =
    card.source === "feedback"
      ? card.github_issue_number
        ? `#${card.github_issue_number}`
        : `${card.feedback_report_count ?? 1} report${(card.feedback_report_count ?? 1) > 1 ? "s" : ""}`
      : card.issue_number !== null
        ? `#${card.issue_number}`
        : "";

  const summary = firstLine(card.rationale) ?? firstLine(card.draft_comment);
  const assigneeCount = card.suggested_assignees?.length ?? 0;
  const suspectCount = card.regression_suspects?.length ?? 0;
  const isStuck = card.status === "pending" && !card.classification;
  const piiTotal = card.pii_redacted
    ? Object.values(card.pii_redacted).reduce((a, b) => a + b, 0)
    : 0;
  const sla = slaStatus(card);
  const correctionsApplied = card.corrections_applied_count ?? 0;

  return (
    <button
      type="button"
      onClick={onOpen}
      className={cn(
        "group relative flex h-full w-full flex-col rounded-lg border bg-card p-5 text-left shadow-elev-1 transition-all duration-150",
        "hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-elev-2",
        active && "border-primary/60 ring-2 ring-ring ring-offset-2 ring-offset-background",
      )}
    >
      {isStuck && (
        <span className="absolute right-3 top-3 rounded-full bg-warning/15 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-warning">
          unclassified
        </span>
      )}

      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 text-[12px] text-muted-foreground">
            {card.source === "feedback" ? (
              <MessageSquareWarning className="h-3.5 w-3.5" />
            ) : (
              <GitPullRequestArrow className="h-3.5 w-3.5" />
            )}
            <span className="truncate font-mono">{card.repo_full_name}</span>
            {issueLabel && (
              <span className="shrink-0 text-muted-foreground/80">
                · {issueLabel}
              </span>
            )}
          </div>
        </div>
      </div>

      <p className="mt-3 line-clamp-3 min-h-[4.5rem] text-[15px] leading-relaxed text-foreground">
        {summary ?? (
          <span className="italic text-muted-foreground">
            no summary yet — open to retry
          </span>
        )}
      </p>

      <div className="mt-4 flex flex-wrap items-center gap-1.5 text-[12px] text-muted-foreground">
        {card.severity && <SeverityPill severity={card.severity} />}
        {card.classification && (
          <span className="rounded-full border px-2 py-0.5">
            {card.classification}
          </span>
        )}
        {piiTotal > 0 && (
          <span
            className="inline-flex items-center gap-1 rounded-full border border-success/40 bg-success/10 px-2 py-0.5 text-success"
            title={`${piiTotal} PII token${piiTotal === 1 ? "" : "s"} scrubbed before the LLM saw this: ${Object.entries(
              card.pii_redacted ?? {},
            )
              .map(([k, v]) => `${k}×${v}`)
              .join(", ")}`}
          >
            <ShieldCheck className="h-3 w-3" />
            PII scrubbed
          </span>
        )}
        {sla && (
          <span
            className={cn(
              "inline-flex items-center gap-1 rounded-full border px-2 py-0.5",
              sla.tint === "breached"
                ? "border-destructive/40 bg-destructive/10 text-destructive"
                : sla.tint === "urgent"
                  ? "border-warning/40 bg-warning/10 text-warning"
                  : "border-border bg-muted/40 text-muted-foreground",
            )}
            title={sla.tooltip}
          >
            <Clock className="h-3 w-3" />
            {sla.label}
          </span>
        )}
        {correctionsApplied > 0 && (
          <span
            className="inline-flex items-center gap-1 rounded-full border border-primary/40 bg-primary/10 px-2 py-0.5 text-primary"
            title={`The orchestrator applied ${correctionsApplied} past operator correction${correctionsApplied === 1 ? "" : "s"} from this repo when classifying and drafting this card.`}
          >
            <Sparkles className="h-3 w-3" />
            learning from {correctionsApplied}
          </span>
        )}
        {typeof card.confidence === "number" && (
          <span className="text-muted-foreground/80">
            conf {card.confidence.toFixed(2)}
          </span>
        )}
      </div>

      <div className="mt-4 flex items-center justify-between gap-2 border-t pt-3 text-[12px] text-muted-foreground">
        <div className="flex items-center gap-3">
          {assigneeCount > 0 && (
            <span className="inline-flex items-center gap-1">
              <UserRound className="h-3 w-3" />
              {assigneeCount}
            </span>
          )}
          {suspectCount > 0 && (
            <span className="inline-flex items-center gap-1 text-warning">
              {suspectCount} suspect{suspectCount === 1 ? "" : "s"}
            </span>
          )}
        </div>
        <time>{relTime(card.created_at)}</time>
      </div>
    </button>
  );
}

type SlaStatus = {
  label: string;
  tint: "breached" | "urgent" | "ok";
  tooltip: string;
};

function slaStatus(card: Card): SlaStatus | null {
  const mins = card.sla_minutes;
  if (!mins) return null;
  const created = new Date(card.created_at).getTime();
  const deadline = created + mins * 60_000;
  const now = Date.now();
  const deltaMin = Math.round((deadline - now) / 60_000);
  if (card.sla_breach_alerted_at || deltaMin < 0) {
    const lateBy = Math.max(1, -deltaMin);
    return {
      label: `breached ${lateBy}m`,
      tint: "breached",
      tooltip: `SLA was ${mins}m; breached ${lateBy} minute${lateBy === 1 ? "" : "s"} ago`,
    };
  }
  const tint: SlaStatus["tint"] = deltaMin <= Math.max(5, Math.floor(mins * 0.1)) ? "urgent" : "ok";
  return {
    label: `SLA in ${deltaMin}m`,
    tint,
    tooltip: `${mins}m SLA, ${deltaMin}m to spare`,
  };
}

function firstLine(s: string | null | undefined): string | null {
  if (!s) return null;
  const trimmed = s.trim();
  if (!trimmed) return null;
  return trimmed.split("\n")[0];
}

function relTime(iso: string): string {
  const then = new Date(iso).getTime();
  const now = Date.now();
  const diff = Math.max(0, now - then);
  const m = Math.floor(diff / 60_000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d ago`;
  return new Date(iso).toLocaleDateString();
}
