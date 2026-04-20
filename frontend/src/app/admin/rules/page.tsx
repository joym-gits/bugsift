"use client";

import { Pencil, Plus, Shield, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import { AppShell, EmptyState, PageHeader, Skeleton } from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api";
import {
  type RuleAction,
  type RuleMatch,
  type TriageRule,
  useCreateRule,
  useDeleteRule,
  useMe,
  useRules,
  useUpdateRule,
} from "@/lib/hooks";
import { cn } from "@/lib/utils";

type Draft = {
  id?: number;
  name: string;
  enabled: boolean;
  priority: number;
  match: RuleMatch;
  action: RuleAction;
};

const EMPTY_DRAFT: Draft = {
  name: "",
  enabled: true,
  priority: 100,
  match: {},
  action: {},
};

export default function AdminRulesPage() {
  const me = useMe();
  const signedIn = Boolean(me.data);
  const isAdmin = me.data?.role === "admin";
  const rules = useRules(signedIn && isAdmin);
  const createRule = useCreateRule();
  const updateRule = useUpdateRule();
  const deleteRule = useDeleteRule();

  const [editing, setEditing] = useState<Draft | null>(null);
  const [err, setErr] = useState<string | null>(null);

  return (
    <AppShell me={me.data ?? null}>
      {!signedIn ? (
        <EmptyState
          icon={Shield}
          title="Sign in to view rules"
          description="Routing rules are admin-only."
        />
      ) : !isAdmin ? (
        <EmptyState
          icon={Shield}
          title="Admin access required"
          description="Only admins can view and edit routing rules."
        />
      ) : (
        <>
          <PageHeader
            title="Routing rules"
            description="Every rule runs after a card is classified. Matching rules add assignees, add labels, route Slack notifications, and set an SLA — additively, priority-ordered (lower number runs first)."
            actions={
              <Button onClick={() => setEditing({ ...EMPTY_DRAFT })}>
                <Plus className="mr-1 h-4 w-4" />
                New rule
              </Button>
            }
          />

          {err && (
            <p className="mb-4 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
              {err}
            </p>
          )}

          {rules.isLoading ? (
            <div className="space-y-3">
              <Skeleton className="h-20 w-full" />
              <Skeleton className="h-20 w-full" />
            </div>
          ) : rules.data && rules.data.length > 0 ? (
            <ul className="space-y-3">
              {rules.data.map((r) => (
                <RuleRow
                  key={r.id}
                  rule={r}
                  onEdit={() => setEditing(toDraft(r))}
                  onDelete={async () => {
                    if (!window.confirm(`Delete rule "${r.name}"?`)) return;
                    try {
                      await deleteRule.mutateAsync(r.id);
                    } catch (e) {
                      setErr(errMessage(e));
                    }
                  }}
                  onToggle={async () => {
                    try {
                      await updateRule.mutateAsync({
                        id: r.id,
                        body: { enabled: !r.enabled },
                      });
                    } catch (e) {
                      setErr(errMessage(e));
                    }
                  }}
                />
              ))}
            </ul>
          ) : (
            <EmptyState
              icon={Shield}
              title="No rules yet"
              description="Create one to auto-assign on severity, notify Slack on classification, or set an SLA on blocker cards."
              action={
                <Button onClick={() => setEditing({ ...EMPTY_DRAFT })}>
                  <Plus className="mr-1 h-4 w-4" />
                  Create first rule
                </Button>
              }
            />
          )}

          {editing && (
            <EditModal
              draft={editing}
              onClose={() => setEditing(null)}
              onSave={async (draft) => {
                setErr(null);
                try {
                  if (draft.id) {
                    await updateRule.mutateAsync({
                      id: draft.id,
                      body: {
                        name: draft.name,
                        enabled: draft.enabled,
                        priority: draft.priority,
                        match: pruneEmpty(draft.match) as RuleMatch,
                        action: pruneEmpty(draft.action) as RuleAction,
                      },
                    });
                  } else {
                    await createRule.mutateAsync({
                      name: draft.name,
                      enabled: draft.enabled,
                      priority: draft.priority,
                      match: pruneEmpty(draft.match) as RuleMatch,
                      action: pruneEmpty(draft.action) as RuleAction,
                    });
                  }
                  setEditing(null);
                } catch (e) {
                  setErr(errMessage(e));
                }
              }}
            />
          )}
        </>
      )}
    </AppShell>
  );
}

function RuleRow({
  rule,
  onEdit,
  onDelete,
  onToggle,
}: {
  rule: TriageRule;
  onEdit: () => void;
  onDelete: () => void;
  onToggle: () => void;
}) {
  return (
    <li
      className={cn(
        "rounded-lg border bg-card p-5 shadow-elev-1 transition-colors",
        !rule.enabled && "opacity-60",
      )}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-medium">{rule.name}</span>
            <span className="rounded-full border px-2 py-0.5 text-[11px] font-mono text-muted-foreground">
              priority {rule.priority}
            </span>
            <button
              type="button"
              onClick={onToggle}
              className={cn(
                "rounded-full border px-2 py-0.5 text-[11px] font-medium",
                rule.enabled
                  ? "border-success/40 bg-success/10 text-success"
                  : "border-muted-foreground/30 bg-muted/30 text-muted-foreground",
              )}
            >
              {rule.enabled ? "Enabled" : "Disabled"}
            </button>
          </div>
          <dl className="mt-3 grid gap-2 text-[13px] sm:grid-cols-2">
            <Section label="When" entries={describe(rule.match)} />
            <Section label="Then" entries={describe(rule.action)} />
          </dl>
        </div>
        <div className="flex shrink-0 gap-1">
          <button
            type="button"
            onClick={onEdit}
            className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
            aria-label="Edit"
          >
            <Pencil className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={onDelete}
            className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
            aria-label="Delete"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>
    </li>
  );
}

function Section({
  label,
  entries,
}: {
  label: string;
  entries: { key: string; value: string }[];
}) {
  return (
    <div>
      <dt className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </dt>
      <dd className="mt-1">
        {entries.length === 0 ? (
          <span className="italic text-muted-foreground">— any —</span>
        ) : (
          <ul className="space-y-0.5">
            {entries.map((e) => (
              <li key={e.key}>
                <span className="text-muted-foreground">{e.key}:</span>{" "}
                <span className="font-mono">{e.value}</span>
              </li>
            ))}
          </ul>
        )}
      </dd>
    </div>
  );
}

function EditModal({
  draft: initial,
  onClose,
  onSave,
}: {
  draft: Draft;
  onClose: () => void;
  onSave: (draft: Draft) => Promise<void>;
}) {
  const [draft, setDraft] = useState<Draft>(initial);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setDraft(initial);
  }, [initial]);

  const patchMatch = (p: Partial<RuleMatch>) =>
    setDraft((d) => ({ ...d, match: { ...d.match, ...p } }));
  const patchAction = (p: Partial<RuleAction>) =>
    setDraft((d) => ({ ...d, action: { ...d.action, ...p } }));

  return (
    <div
      className="fixed inset-0 z-40 flex items-start justify-center overflow-y-auto bg-foreground/30 p-6 backdrop-blur-[2px]"
      onClick={onClose}
    >
      <div
        className="mt-12 w-full max-w-2xl rounded-lg border bg-background p-6 shadow-elev-3"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-semibold">
          {draft.id ? "Edit rule" : "New rule"}
        </h2>

        <div className="mt-5 space-y-5">
          <div className="grid gap-3 sm:grid-cols-[1fr_140px]">
            <div className="space-y-1">
              <Label htmlFor="r-name">Name</Label>
              <Input
                id="r-name"
                value={draft.name}
                onChange={(e) =>
                  setDraft((d) => ({ ...d, name: e.target.value }))
                }
                placeholder="Blockers page the sec team"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="r-priority">Priority</Label>
              <Input
                id="r-priority"
                type="number"
                min={1}
                max={9999}
                value={draft.priority}
                onChange={(e) =>
                  setDraft((d) => ({
                    ...d,
                    priority: Math.max(1, Number(e.target.value) || 100),
                  }))
                }
              />
            </div>
          </div>

          <Fieldset title="Match (all must hold)">
            <Row
              label="Classification"
              value={draft.match.classification ?? ""}
              options={["", "bug", "feature-request", "question", "docs", "spam", "other"]}
              onChange={(v) => patchMatch({ classification: v || undefined })}
            />
            <Row
              label="Severity"
              value={draft.match.severity ?? ""}
              options={["", "blocker", "high", "medium", "low"]}
              onChange={(v) => patchMatch({ severity: v || undefined })}
            />
            <Row
              label="Source"
              value={draft.match.source ?? ""}
              options={["", "github", "feedback"]}
              onChange={(v) => patchMatch({ source: v || undefined })}
            />
            <Row
              label="Repo glob"
              value={draft.match.repo_full_name_glob ?? ""}
              placeholder="my-org/* or my-org/repo"
              onChange={(v) => patchMatch({ repo_full_name_glob: v || undefined })}
            />
            <Row
              label="Min confidence"
              type="number"
              step="0.05"
              min={0}
              max={1}
              value={draft.match.min_confidence ?? ""}
              onChange={(v) =>
                patchMatch({
                  min_confidence: v === "" ? undefined : Number(v),
                })
              }
            />
          </Fieldset>

          <Fieldset title="Then (accumulated across matching rules)">
            <Row
              label="Add assignees"
              value={(draft.action.assign ?? []).join(", ")}
              placeholder="alice, @bob"
              onChange={(v) =>
                patchAction({
                  assign: v
                    .split(/[\s,]+/)
                    .map((s) => s.replace(/^@/, "").trim())
                    .filter(Boolean),
                })
              }
            />
            <Row
              label="Add labels"
              value={(draft.action.add_labels ?? []).join(", ")}
              placeholder="needs-triage, security"
              onChange={(v) =>
                patchAction({
                  add_labels: v
                    .split(/[,]+/)
                    .map((s) => s.trim())
                    .filter(Boolean),
                })
              }
            />
            <Row
              label="SLA minutes"
              type="number"
              min={1}
              value={draft.action.sla_minutes ?? ""}
              placeholder="60"
              onChange={(v) =>
                patchAction({
                  sla_minutes: v === "" ? undefined : Math.max(1, Number(v)),
                })
              }
            />
            <Row
              label="Notify Slack destination id"
              type="number"
              min={1}
              value={draft.action.notify_slack ?? ""}
              placeholder="from /settings Slack section"
              onChange={(v) =>
                patchAction({
                  notify_slack: v === "" ? undefined : Number(v),
                })
              }
            />
          </Fieldset>

          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={draft.enabled}
              onChange={(e) =>
                setDraft((d) => ({ ...d, enabled: e.target.checked }))
              }
            />
            Enabled
          </label>
        </div>

        <div className="mt-6 flex items-center justify-end gap-2">
          <Button variant="outline" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button
            onClick={async () => {
              if (!draft.name.trim()) return;
              setSaving(true);
              try {
                await onSave(draft);
              } finally {
                setSaving(false);
              }
            }}
            disabled={saving || !draft.name.trim()}
          >
            {saving ? "saving…" : draft.id ? "Save rule" : "Create rule"}
          </Button>
        </div>
      </div>
    </div>
  );
}

function Fieldset({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <fieldset className="rounded-md border p-4">
      <legend className="px-1 text-[12px] font-medium uppercase tracking-wider text-muted-foreground">
        {title}
      </legend>
      <div className="space-y-3">{children}</div>
    </fieldset>
  );
}

function Row({
  label,
  value,
  options,
  placeholder,
  type,
  min,
  max,
  step,
  onChange,
}: {
  label: string;
  value: string | number;
  options?: string[];
  placeholder?: string;
  type?: string;
  min?: number;
  max?: number;
  step?: string;
  onChange: (v: string) => void;
}) {
  const v = typeof value === "number" ? String(value) : value;
  return (
    <div className="grid grid-cols-[140px_1fr] items-center gap-3">
      <Label className="text-[12px] text-muted-foreground">{label}</Label>
      {options ? (
        <select
          value={v}
          onChange={(e) => onChange(e.target.value)}
          className="h-9 rounded-md border border-input bg-background px-2 text-sm"
        >
          {options.map((o) => (
            <option key={o || "any"} value={o}>
              {o || "— any —"}
            </option>
          ))}
        </select>
      ) : (
        <Input
          type={type ?? "text"}
          min={min}
          max={max}
          step={step}
          value={v}
          placeholder={placeholder}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
    </div>
  );
}

function describe(obj: Record<string, unknown>): { key: string; value: string }[] {
  return Object.entries(obj)
    .filter(([, v]) => v !== undefined && v !== "" && v !== null && !(Array.isArray(v) && v.length === 0))
    .map(([k, v]) => ({
      key: k,
      value: Array.isArray(v) ? v.join(", ") : String(v),
    }));
}

function pruneEmpty(obj: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(obj)) {
    if (v === undefined || v === "" || v === null) continue;
    if (Array.isArray(v) && v.length === 0) continue;
    out[k] = v;
  }
  return out;
}

function toDraft(r: TriageRule): Draft {
  return {
    id: r.id,
    name: r.name,
    enabled: r.enabled,
    priority: r.priority,
    match: { ...r.match },
    action: { ...r.action },
  };
}

function errMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return "request failed";
}
