"use client";

import Link from "next/link";

import { Button } from "@/components/ui/button";
import { API_BASE_URL } from "@/lib/api";
import { useLogout, useMe } from "@/lib/hooks";

export default function DashboardPage() {
  const me = useMe();
  const logout = useLogout();

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
              <Link
                href="/settings"
                className="text-sm underline underline-offset-4"
              >
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

      <section className="rounded-lg border bg-card p-6 text-card-foreground shadow-sm">
        <h2 className="text-lg font-medium">
          {me.data ? "Triage queue" : "Phase 2 — database and auth"}
        </h2>
        <p className="mt-2 text-sm text-muted-foreground">
          {me.data
            ? "Webhook ingestion lands in phase 3. Until then the queue is empty."
            : "Sign in with GitHub to see your dashboard, configure repos, and store your LLM API keys."}
        </p>
        <div className="mt-4 flex gap-2">
          <Button variant="default" disabled>
            No triage cards yet
          </Button>
          <a
            href={`${API_BASE_URL}/health`}
            className="inline-flex h-10 items-center justify-center rounded-md border border-input bg-background px-4 py-2 text-sm font-medium hover:bg-accent hover:text-accent-foreground"
          >
            Check backend
          </a>
        </div>
      </section>
    </main>
  );
}
