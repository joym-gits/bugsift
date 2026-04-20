"use client";

import { Shield, User as UserIcon } from "lucide-react";
import { useState } from "react";

import { AppShell, EmptyState, PageHeader, Skeleton } from "@/components/AppShell";
import { ApiError } from "@/lib/api";
import {
  type Role,
  useAdminUsers,
  useMe,
  useUpdateUserRole,
} from "@/lib/hooks";

const ROLES: { value: Role; label: string; hint: string }[] = [
  { value: "admin", label: "Admin", hint: "Manages users + GitHub App + audit log." },
  { value: "triager", label: "Triager", hint: "Approves, skips, edits cards. No user admin." },
  { value: "viewer", label: "Viewer", hint: "Read-only. Can see queue + history." },
];

export default function AdminUsersPage() {
  const me = useMe();
  const signedIn = Boolean(me.data);
  const isAdmin = me.data?.role === "admin";
  const users = useAdminUsers(signedIn && isAdmin);
  const updateRole = useUpdateUserRole();
  const [err, setErr] = useState<string | null>(null);

  return (
    <AppShell me={me.data ?? null}>
      {!signedIn ? (
        <EmptyState
          icon={Shield}
          title="Sign in to view user admin"
          description="This page is only visible to administrators."
        />
      ) : !isAdmin ? (
        <EmptyState
          icon={Shield}
          title="Admin access required"
          description="Ask an existing admin to promote your account before you can manage users."
        />
      ) : (
        <>
          <PageHeader
            title="Users"
            description="Every account that has signed into this bugsift deployment. Change roles to grant or revoke privileges."
          />

          {err && (
            <p className="mb-4 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
              {err}
            </p>
          )}

          {users.isLoading ? (
            <div className="space-y-2">
              <Skeleton className="h-14 w-full" />
              <Skeleton className="h-14 w-full" />
            </div>
          ) : users.data && users.data.length > 0 ? (
            <div className="rounded-lg border bg-card shadow-elev-1">
              <table className="w-full text-sm">
                <thead className="border-b bg-muted/30 text-left text-[12px] uppercase tracking-wider text-muted-foreground">
                  <tr>
                    <th className="px-5 py-3">User</th>
                    <th className="px-5 py-3">Joined</th>
                    <th className="px-5 py-3">Role</th>
                  </tr>
                </thead>
                <tbody>
                  {users.data.map((u) => {
                    const isSelf = me.data?.id === u.id;
                    return (
                      <tr key={u.id} className="border-b last:border-0">
                        <td className="px-5 py-4">
                          <div className="flex items-center gap-3">
                            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-muted text-[11px] font-semibold text-muted-foreground">
                              <UserIcon className="h-4 w-4" />
                            </div>
                            <div>
                              <div className="font-medium">
                                {u.github_login}
                                {isSelf && (
                                  <span className="ml-1.5 text-[11px] text-muted-foreground">
                                    (you)
                                  </span>
                                )}
                              </div>
                              {u.email && (
                                <div className="text-[12px] text-muted-foreground">
                                  {u.email}
                                </div>
                              )}
                            </div>
                          </div>
                        </td>
                        <td className="px-5 py-4 text-muted-foreground">
                          {new Date(u.created_at).toLocaleDateString()}
                        </td>
                        <td className="px-5 py-4">
                          <div className="flex items-center gap-2">
                            <select
                              value={u.role}
                              onChange={async (e) => {
                                setErr(null);
                                try {
                                  await updateRole.mutateAsync({
                                    userId: u.id,
                                    role: e.target.value as Role,
                                  });
                                } catch (e) {
                                  if (e instanceof ApiError) setErr(e.message);
                                  else if (e instanceof Error) setErr(e.message);
                                  else setErr("role change failed");
                                }
                              }}
                              disabled={updateRole.isPending}
                              className="h-9 rounded-md border border-input bg-background px-2 text-sm"
                            >
                              {ROLES.map((r) => (
                                <option key={r.value} value={r.value}>
                                  {r.label}
                                </option>
                              ))}
                            </select>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState
              icon={UserIcon}
              title="No users yet"
              description="Sign-ins on this deployment will appear here."
            />
          )}

          <section className="mt-8 rounded-lg border bg-card p-6 shadow-elev-1">
            <h2 className="text-base font-medium">What each role can do</h2>
            <dl className="mt-4 space-y-3">
              {ROLES.map((r) => (
                <div key={r.value} className="flex gap-3">
                  <dt className="w-24 shrink-0 text-sm font-medium">{r.label}</dt>
                  <dd className="text-sm text-muted-foreground">{r.hint}</dd>
                </div>
              ))}
            </dl>
          </section>
        </>
      )}
    </AppShell>
  );
}
