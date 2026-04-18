"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { TriageCard } from "@/components/TriageCard";
import { API_BASE_URL } from "@/lib/api";
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

  if (me.isLoading) {
    return (
      <main className="container mx-auto py-16 text-muted-foreground">loading…</main>
    );
  }

  if (!signedIn) {
    return (
      <main className="container mx-auto flex min-h-screen flex-col justify-center gap-6 py-16">
        <h1 className="text-3xl font-semibold tracking-tight">History</h1>
        <p className="text-muted-foreground">Sign in to see past triage decisions.</p>
        <a
          href={`${API_BASE_URL}/auth/github/start`}
          className="inline-flex h-10 w-fit items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          Sign in with GitHub
        </a>
      </main>
    );
  }

  return (
    <main className="container mx-auto flex flex-col gap-6 py-16">
      <header className="flex items-center justify-between">
        <div className="space-y-1">
          <h1 className="text-3xl font-semibold tracking-tight">History</h1>
          <p className="text-sm text-muted-foreground">
            Every triage card, read-only. Filters are AND-combined.
          </p>
        </div>
        <Link
          href="/dashboard"
          className="text-sm underline underline-offset-4"
        >
          ← Dashboard
        </Link>
      </header>

      <section className="flex flex-wrap gap-3 rounded-lg border bg-card p-4 shadow-sm">
        <Filter
          id="status"
          label="Status"
          value={status}
          onChange={setStatus}
          options={STATUS_OPTIONS}
        />
        <Filter
          id="classification"
          label="Classification"
          value={classification}
          onChange={setClassification}
          options={CLASSIFICATION_OPTIONS}
        />
        <Filter
          id="verdict"
          label="Reproduction verdict"
          value={verdict}
          onChange={setVerdict}
          options={VERDICT_OPTIONS}
        />
        <div className="flex items-end">
          <span className="text-xs text-muted-foreground">
            showing {cards.data?.length ?? 0} card
            {cards.data && cards.data.length === 1 ? "" : "s"}
          </span>
        </div>
      </section>

      <section>
        {cards.isLoading ? (
          <p className="text-sm text-muted-foreground">loading…</p>
        ) : cards.data && cards.data.length > 0 ? (
          <ul className="space-y-3">
            {cards.data.map((c) => (
              <li key={c.id}>
                <TriageCard card={c} />
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">
            No cards match these filters.
          </p>
        )}
      </section>
    </main>
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
