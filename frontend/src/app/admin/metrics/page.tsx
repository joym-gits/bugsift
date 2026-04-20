"use client";

import { BarChart3, Shield } from "lucide-react";
import { useState } from "react";

import { AppShell, EmptyState, PageHeader, Skeleton } from "@/components/AppShell";
import { type CountByKey, type MetricsResponse, type TimeSeriesPoint, useMe, useMetrics } from "@/lib/hooks";
import { cn } from "@/lib/utils";

const WINDOWS = [7, 14, 30, 90];

export default function AdminMetricsPage() {
  const me = useMe();
  const signedIn = Boolean(me.data);
  const isAdmin = me.data?.role === "admin";
  const [days, setDays] = useState(30);
  const metrics = useMetrics(signedIn && isAdmin, days);

  return (
    <AppShell me={me.data ?? null}>
      {!signedIn ? (
        <EmptyState
          icon={Shield}
          title="Sign in to view metrics"
          description="This page is only visible to administrators."
        />
      ) : !isAdmin ? (
        <EmptyState
          icon={Shield}
          title="Admin access required"
          description="Operational metrics are restricted to admins."
        />
      ) : (
        <>
          <PageHeader
            title="Metrics"
            description="Throughput, cost, and triage outcomes across every repo on this deployment."
            actions={
              <div className="flex items-center gap-1 rounded-md border bg-background p-1">
                {WINDOWS.map((d) => (
                  <button
                    key={d}
                    type="button"
                    onClick={() => setDays(d)}
                    className={cn(
                      "rounded-[4px] px-2.5 py-1 text-[12px] font-medium transition-colors",
                      d === days
                        ? "bg-primary text-primary-foreground"
                        : "text-muted-foreground hover:bg-accent",
                    )}
                  >
                    {d}d
                  </button>
                ))}
              </div>
            }
          />

          {metrics.isLoading || !metrics.data ? (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <Skeleton className="h-24 w-full" />
              <Skeleton className="h-24 w-full" />
              <Skeleton className="h-24 w-full" />
              <Skeleton className="h-24 w-full" />
            </div>
          ) : (
            <MetricsBody data={metrics.data} days={days} />
          )}
        </>
      )}
    </AppShell>
  );
}

function MetricsBody({ data, days }: { data: MetricsResponse; days: number }) {
  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Stat
          label="Cards created"
          value={data.cards_created.toLocaleString()}
          hint={`last ${days} days`}
        />
        <Stat
          label="LLM spend"
          value={`$${data.total_cost_usd.toFixed(2)}`}
          hint="across all providers"
        />
        <Stat
          label="Approval rate"
          value={`${Math.round(data.approval_rate * 100)}%`}
          hint="of decided cards"
        />
        <Stat
          label="PII scrubbed"
          value={`${Math.round(data.pii_scrub_rate * 100)}%`}
          hint="of cards in window"
        />
      </div>

      {data.sla_compliance_rate !== null && (
        <div className="grid gap-4 md:grid-cols-2">
          <Stat
            label="SLA compliance"
            value={`${Math.round(data.sla_compliance_rate * 100)}%`}
            hint={`across ${data.sla_cards_total} card${data.sla_cards_total === 1 ? "" : "s"} with an SLA`}
          />
          <Stat
            label="SLA cards"
            value={data.sla_cards_total.toLocaleString()}
            hint={`created in last ${days} days`}
          />
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <ChartCard title="Cards per day">
          <Sparkline series={data.cards_by_day} format={(v) => `${v.toFixed(0)} cards`} />
        </ChartCard>
        <ChartCard title="LLM spend per day ($)">
          <Sparkline
            series={data.cost_by_day_usd}
            format={(v) => `$${v.toFixed(3)}`}
            tint="info"
          />
        </ChartCard>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <ChartCard title="Outcome mix">
          <OutcomeBar mix={data.outcome_mix} />
        </ChartCard>
        <ChartCard title="Cost by step ($)">
          <HorizontalBars rows={data.cost_by_step_usd} formatter={(v) => `$${v.toFixed(3)}`} />
        </ChartCard>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <ChartCard title="Cost by provider ($)">
          <HorizontalBars rows={data.cost_by_provider_usd} formatter={(v) => `$${v.toFixed(3)}`} />
        </ChartCard>
        <ChartCard title="Cost by model ($)">
          <HorizontalBars rows={data.cost_by_model_usd} formatter={(v) => `$${v.toFixed(3)}`} />
        </ChartCard>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <ChartCard title="Classifications">
          <HorizontalBars rows={data.classification_mix} formatter={(v) => v.toFixed(0)} />
        </ChartCard>
        <ChartCard title="Severity">
          <HorizontalBars rows={data.severity_mix} formatter={(v) => v.toFixed(0)} />
        </ChartCard>
      </div>
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="rounded-lg border bg-card p-5 shadow-elev-1">
      <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div className="mt-2 text-2xl font-semibold tracking-tight">{value}</div>
      <div className="mt-1 text-[12px] text-muted-foreground">{hint}</div>
    </div>
  );
}

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border bg-card p-5 shadow-elev-1">
      <div className="mb-4 text-sm font-medium">{title}</div>
      {children}
    </div>
  );
}

function Sparkline({
  series,
  format,
  tint = "primary",
}: {
  series: TimeSeriesPoint[];
  format: (v: number) => string;
  tint?: "primary" | "info";
}) {
  if (series.length === 0) {
    return <div className="h-24 text-sm text-muted-foreground">no data</div>;
  }
  const max = Math.max(1, ...series.map((p) => p.value));
  const width = 600;
  const height = 72;
  const step = width / Math.max(1, series.length - 1);
  const points = series
    .map((p, i) => `${(i * step).toFixed(2)},${(height - (p.value / max) * height).toFixed(2)}`)
    .join(" ");
  const last = series[series.length - 1]?.value ?? 0;
  const stroke = tint === "info" ? "hsl(var(--info))" : "hsl(var(--primary))";
  return (
    <div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        className="h-24 w-full"
      >
        <polyline
          fill="none"
          stroke={stroke}
          strokeWidth="2"
          points={points}
        />
      </svg>
      <div className="mt-2 flex items-center justify-between text-[11px] text-muted-foreground">
        <span>{series[0]?.date}</span>
        <span className="font-medium text-foreground">latest: {format(last)}</span>
        <span>{series[series.length - 1]?.date}</span>
      </div>
    </div>
  );
}

function OutcomeBar({ mix }: { mix: { pending: number; posted: number; skipped: number } }) {
  const total = Math.max(1, mix.pending + mix.posted + mix.skipped);
  const seg = (n: number) => (n / total) * 100;
  return (
    <div>
      <div className="flex h-3 w-full overflow-hidden rounded-full border bg-muted">
        <div
          className="bg-success"
          style={{ width: `${seg(mix.posted)}%` }}
          title={`posted: ${mix.posted}`}
        />
        <div
          className="bg-muted-foreground/40"
          style={{ width: `${seg(mix.skipped)}%` }}
          title={`skipped: ${mix.skipped}`}
        />
        <div
          className="bg-warning"
          style={{ width: `${seg(mix.pending)}%` }}
          title={`pending: ${mix.pending}`}
        />
      </div>
      <div className="mt-3 grid grid-cols-3 gap-2 text-[12px]">
        <LegendRow color="bg-success" label="Posted" value={mix.posted} />
        <LegendRow color="bg-muted-foreground/40" label="Skipped" value={mix.skipped} />
        <LegendRow color="bg-warning" label="Pending" value={mix.pending} />
      </div>
    </div>
  );
}

function LegendRow({ color, label, value }: { color: string; label: string; value: number }) {
  return (
    <div className="flex items-center gap-2">
      <span className={cn("h-2 w-2 rounded-full", color)} />
      <span className="text-muted-foreground">{label}</span>
      <span className="ml-auto font-medium">{value}</span>
    </div>
  );
}

function HorizontalBars({
  rows,
  formatter,
}: {
  rows: CountByKey[];
  formatter: (v: number) => string;
}) {
  if (rows.length === 0) {
    return <div className="text-sm text-muted-foreground">no data in window</div>;
  }
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <div className="space-y-2">
      {rows.slice(0, 8).map((r) => (
        <div key={r.key} className="text-[13px]">
          <div className="flex items-baseline justify-between gap-2">
            <span className="truncate font-medium">{r.key}</span>
            <span className="shrink-0 font-mono text-[12px] text-muted-foreground">
              {formatter(r.value)}
            </span>
          </div>
          <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-muted">
            <div
              className="h-full bg-primary/60"
              style={{ width: `${(r.value / max) * 100}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
