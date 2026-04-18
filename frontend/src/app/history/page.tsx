"use client";

import { useMemo, useState } from "react";
import { History as HistoryIcon } from "lucide-react";

import { AppShell, EmptyState, PageHeader, Skeleton } from "@/components/AppShell";
import { TriageCard } from "@/components/TriageCard";
import { type CardFilters, useCards, useMe } from "@/lib/hooks";

const CLASSIFICATION_OPTIONS = [
  { value: "", label: "any classification" },
  { value: "bug", label: "bug" },
  { value: "feature-request", label: "feature-request" },
  { value: "question", label: "question" },
  { value: "docs", label: "docs" },
  { value: "spam", label: "spam" },
  { value: "other", label: "other" },
];

const STATUS_OPTIONS = [
  { value: "", label: "any status" },
  { value: "pending", label: "pending" },
  { value: "posted", label: "posted" },
  { value: "skipped", label: "skipped" },
];

const VERDICT_OPTIONS = [
  { value: "", label: "any verdict" },
  { value: "reproduced", label: "reproduced" },
  { value: "not_reproduced", label: "not reproduced" },
  { value: "insufficient_info", label: "insufficient info" },
  { value: "unsupported_language", label: "unsupported language" },
  { value: "sandbox_error", label: "sandbox error" },
];

export default function HistoryPage() {
  const me = useMe();
  const signedIn = Boolean(me.data);
  const [status, setStatus] = useState("");
  const [classification, setClassification] = useState("");
  const [verdict, setVerdict] = useState("");
  const filters: CardFilters = useMemo(
    () => ({
      status: status || undefined,
      classification: classification || undefined,
      verdict: verdict || undefined,
      limit: 200,
    }),
    [status, classification, verdict],
  );
  const cards = useCards(signedIn, filters);

  return (
    <AppShell me={me.data ?? null}>
      {!signedIn ? (
        <EmptyState
          icon={HistoryIcon}
          title="Sign in to see history"
          description="Every triage decision lives here — filterable by status, classification, and reproduction verdict."
        />
      ) : (
        <>
          <PageHeader
            title="History"
            description="Every card, read-only. Filters are AND-combined."
          />

          <section className="mb-6 flex flex-wrap gap-3 rounded-lg border bg-card p-4 shadow-sm">
            <Filter id="status" label="Status" value={status} onChange={setStatus} options={STATUS_OPTIONS} />
            <Filter
              id="classification"
              label="Classification"
              value={classification}
              onChange={setClassification}
              options={CLASSIFICATION_OPTIONS}
            />
            <Filter id="verdict" label="Verdict" value={verdict} onChange={setVerdict} options={VERDICT_OPTIONS} />
            <div className="flex flex-1 items-end justify-end">
              <span className="text-xs text-muted-foreground">
                showing {cards.data?.length ?? 0} card
                {cards.data && cards.data.length === 1 ? "" : "s"}
              </span>
            </div>
          </section>

          {cards.isLoading ? (
            <div className="space-y-3">
              <Skeleton className="h-32 w-full" />
              <Skeleton className="h-32 w-full" />
            </div>
          ) : cards.data && cards.data.length > 0 ? (
            <ul className="space-y-3">
              {cards.data.map((c) => (
                <li key={c.id}>
                  <TriageCard card={c} />
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              icon={HistoryIcon}
              title="No matching cards"
              description="Try loosening the filters above. If your installation is fresh, open an issue on an installed repo to start building history."
            />
          )}
        </>
      )}
    </AppShell>
  );
}

function Filter({
  id,
  label,
  value,
  onChange,
  options,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <div className="flex min-w-[180px] flex-col gap-1">
      <label htmlFor={id} className="text-xs font-medium text-muted-foreground">
        {label}
      </label>
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-9 rounded-md border border-input bg-background px-2 text-sm"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}
