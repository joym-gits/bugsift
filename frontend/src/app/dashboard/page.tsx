"use client";

import Link from "next/link";

import { Button } from "@/components/ui/button";
import { TriageCard } from "@/components/TriageCard";
import { API_BASE_URL } from "@/lib/api";
import { useCards, useLogout, useMe, useRepos } from "@/lib/hooks";

export default function DashboardPage() {
  const me = useMe();
  const logout = useLogout();
  const signedIn = Boolean(me.data);
  const cards = useCards(signedIn);
  const repos = useRepos(signedIn);

  return (
    <main className="container mx-auto flex min-h-screen flex-col gap-6 py-16">
      <header className="flex items-start justify-between">
        <div className="space-y-2">
          <h1 className="text-4xl font-semibold tracking-tight">bugsift</h1>
          <p className="text-muted-foreground">Sift signal from noise in your issue tracker.</p>
        </div>
        <div className="flex items-center gap-3">
          {me.isLoading ? (
            <span className="text-sm text-muted-foreground">loading…</span>
          ) : me.data ? (
            <>
              <span className="text-sm text-muted-foreground">
                signed in as <strong className="font-medium">{me.data.github_login}</strong>
              </span>
              <Link href="/settings" className="text-sm underline underline-offset-4">
                Settings
              </Link>
              <Button variant="outline" size="sm" onClick={() => logout.mutate()}>
                Log out
              </Button>
            </>
          ) : (
            <a
              href={`${API_BASE_URL}/auth/github/start`}
              className="inline-flex h-10 items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
            >
              Sign in with GitHub
            </a>
          )}
        </div>
      </header>

      {!signedIn ? (
        <SignedOutPanel />
      ) : (
        <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
          <aside className="rounded-lg border bg-card p-4 text-card-foreground shadow-sm">
            <h2 className="text-sm font-medium text-muted-foreground">Installed repos</h2>
            {repos.isLoading ? (
              <p className="mt-3 text-sm text-muted-foreground">loading…</p>
            ) : repos.data && repos.data.length > 0 ? (
              <ul className="mt-3 space-y-2 text-sm">
                {repos.data.map((r) => (
                  <li key={r.id} className="flex items-center justify-between gap-2">
                    <span className="truncate font-medium">{r.full_name}</span>
                    <span className="text-xs text-muted-foreground">{r.indexing_status}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-3 text-sm text-muted-foreground">
                Install the GitHub App on a repo to get started.
              </p>
            )}
          </aside>

          <section className="rounded-lg border bg-card p-6 text-card-foreground shadow-sm">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-medium">Triage queue</h2>
              <span className="text-xs text-muted-foreground">
                {cards.data?.length ?? 0} card
                {cards.data && cards.data.length === 1 ? "" : "s"}
              </span>
            </div>
            {cards.isLoading ? (
              <p className="mt-3 text-sm text-muted-foreground">loading…</p>
            ) : cards.data && cards.data.length > 0 ? (
              <ul className="mt-4 space-y-3">
                {cards.data.map((c) => (
                  <li key={c.id}>
                    <TriageCard card={c} />
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-3 text-sm text-muted-foreground">
                No cards yet. Open an issue on an installed repo to see one appear.
              </p>
            )}
          </section>
        </div>
      )}
    </main>
  );
}

function SignedOutPanel() {
  return (
    <section className="rounded-lg border bg-card p-6 text-card-foreground shadow-sm">
      <h2 className="text-lg font-medium">Phase 3 — webhooks and installations</h2>
      <p className="mt-2 text-sm text-muted-foreground">
        Sign in with GitHub, then install the bugsift App on a repo. Issues opened on that
        repo will appear here as triage cards.
      </p>
      <div className="mt-4">
        <a
          href={`${API_BASE_URL}/health`}
          className="inline-flex h-10 items-center justify-center rounded-md border border-input bg-background px-4 py-2 text-sm font-medium hover:bg-accent hover:text-accent-foreground"
        >
          Check backend
        </a>
      </div>
    </section>
  );
}
