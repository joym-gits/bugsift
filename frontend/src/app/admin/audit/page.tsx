"use client";

import { Download, Shield } from "lucide-react";
import { useState } from "react";

import { AppShell, EmptyState, PageHeader, Skeleton } from "@/components/AppShell";
import { API_BASE_URL } from "@/lib/api";
import { useAuditActions, useAuditEvents, useMe } from "@/lib/hooks";

export default function AuditLogPage() {
  const me = useMe();
  const signedIn = Boolean(me.data);
  const isAdmin = me.data?.role === "admin";

  const [actor, setActor] = useState("");
  const [action, setAction] = useState("");
  const [targetType, setTargetType] = useState("");
  const filters = {
    actor: actor.trim() || undefined,
    action: action || undefined,
    target_type: targetType.trim() || undefined,
    limit: 500,
  };
  const events = useAuditEvents(signedIn && isAdmin, filters);
  const actions = useAuditActions(signedIn && isAdmin);

  const exportParams = new URLSearchParams();
  if (actor.trim()) exportParams.set("actor", actor.trim());
  if (action) exportParams.set("action", action);
  if (targetType.trim()) exportParams.set("target_type", targetType.trim());
  const exportHref = `${API_BASE_URL}/audit/export.csv?${exportParams.toString()}`;

  return (
    <AppShell me={me.data ?? null}>
      {!signedIn ? (
        <EmptyState
          icon={Shield}
          title="Sign in to view the audit log"
          description="This page is only visible to administrators."
        />
      ) : !isAdmin ? (
        <EmptyState
          icon={Shield}
          title="Admin access required"
          description="The audit log is restricted to admins."
        />
      ) : (
        <>
          <PageHeader
            title="Audit log"
            description="Every security- or ops-relevant action on this deployment. Append-only — nothing here can be edited after the fact."
            actions={
              <a
                href={exportHref}
                className="inline-flex h-9 items-center gap-1.5 rounded-md border border-input bg-background px-3 text-sm font-medium hover:bg-accent hover:text-accent-foreground"
              >
                <Download className="h-3.5 w-3.5" />
                Export CSV
              </a>
            }
          />

          <section className="mb-6 flex flex-wrap gap-3 rounded-lg border bg-card p-4 shadow-elev-1">
            <div className="flex min-w-[180px] flex-col gap-1">
              <label className="text-xs font-medium text-muted-foreground" htmlFor="f-actor">
                Actor (github login)
              </label>
              <input
                id="f-actor"
                value={actor}
                onChange={(e) => setActor(e.target.value)}
                placeholder="e.g. joym-gits"
                className="h-9 rounded-md border border-input bg-background px-2 text-sm"
              />
            </div>
            <div className="flex min-w-[180px] flex-col gap-1">
              <label className="text-xs font-medium text-muted-foreground" htmlFor="f-action">
                Action
              </label>
              <select
                id="f-action"
                value={action}
                onChange={(e) => setAction(e.target.value)}
                className="h-9 rounded-md border border-input bg-background px-2 text-sm"
              >
                <option value="">any action</option>
                {(actions.data ?? []).map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex min-w-[180px] flex-col gap-1">
              <label className="text-xs font-medium text-muted-foreground" htmlFor="f-target">
                Target type
              </label>
              <input
                id="f-target"
                value={targetType}
                onChange={(e) => setTargetType(e.target.value)}
                placeholder="e.g. card, user, key"
                className="h-9 rounded-md border border-input bg-background px-2 text-sm"
              />
            </div>
            <div className="flex flex-1 items-end justify-end">
              <span className="text-xs text-muted-foreground">
                {events.data?.length ?? 0} event
                {events.data?.length === 1 ? "" : "s"}
              </span>
            </div>
          </section>

          {events.isLoading ? (
            <div className="space-y-2">
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
            </div>
          ) : events.data && events.data.length > 0 ? (
            <div className="overflow-x-auto rounded-lg border bg-card shadow-elev-1">
              <table className="w-full text-sm">
                <thead className="border-b bg-muted/30 text-left text-[12px] uppercase tracking-wider text-muted-foreground">
                  <tr>
                    <th className="px-5 py-3">When</th>
                    <th className="px-5 py-3">Actor</th>
                    <th className="px-5 py-3">Action</th>
                    <th className="px-5 py-3">Target</th>
                    <th className="px-5 py-3">Summary</th>
                    <th className="px-5 py-3">IP</th>
                  </tr>
                </thead>
                <tbody>
                  {events.data.map((e) => (
                    <tr key={e.id} className="border-b last:border-0 align-top">
                      <td className="whitespace-nowrap px-5 py-3 text-muted-foreground">
                        {new Date(e.created_at).toLocaleString()}
                      </td>
                      <td className="whitespace-nowrap px-5 py-3 font-mono text-[12px]">
                        {e.actor_login}
                      </td>
                      <td className="whitespace-nowrap px-5 py-3">
                        <span className="rounded-full border px-2 py-0.5 text-[11px] font-medium">
                          {e.action}
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-5 py-3 font-mono text-[12px] text-muted-foreground">
                        {e.target_type}
                        {e.target_id ? `:${e.target_id}` : ""}
                      </td>
                      <td className="px-5 py-3">{e.summary}</td>
                      <td className="whitespace-nowrap px-5 py-3 font-mono text-[11px] text-muted-foreground">
                        {e.request_ip ?? "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState
              icon={Shield}
              title="No matching events"
              description="Try loosening the filters above. Actions hit the log as soon as they happen."
            />
          )}
        </>
      )}
    </AppShell>
  );
}
