"use client";

import Link from "next/link";
import { Inbox, GitBranch, Rocket, ArrowRight, RefreshCw } from "lucide-react";

import { AppShell, EmptyState, PageHeader, Skeleton } from "@/components/AppShell";
import { TriageCard } from "@/components/TriageCard";
import { Button } from "@/components/ui/button";
import { API_BASE_URL } from "@/lib/api";
import {
  type Repo,
  useAppStatus,
  useCards,
  useMe,
  useRepos,
  useRerunCard,
} from "@/lib/hooks";

export default function DashboardPage() {
  const me = useMe();
  const signedIn = Boolean(me.data);
  const cards = useCards(signedIn, { status: "pending", limit: 50 });
  const repos = useRepos(signedIn);
  // Public endpoint — call it even signed-out so we know whether to show
  // the first-run setup CTA vs a bare sign-in button.
  const appStatus = useAppStatus(true);
  const appConfigured = appStatus.data?.configured ?? false;

  return (
    <AppShell me={me.data ?? null}>
      {!signedIn ? (
        <SignedOutHero appConfigured={appConfigured} />
      ) : (
        <>
          <PageHeader
            title="Triage queue"
            description={
              cards.data
                ? `${cards.data.length} card${cards.data.length === 1 ? "" : "s"} waiting on you`
                : "loading…"
            }
          />

          {appStatus.data && !appStatus.data.configured && (
            <OnboardingBanner />
          )}

          {cards.data && cards.data.some((c) => !c.classification) && (
            <StuckCardsBanner
              count={cards.data.filter((c) => !c.classification).length}
              ids={cards.data.filter((c) => !c.classification).map((c) => c.id)}
            />
          )}

          <div className="grid gap-6 lg:grid-cols-[280px_1fr]">
            <aside className="space-y-4">
              <RepoList loading={repos.isLoading} repos={repos.data ?? []} />
            </aside>

            <section>
              {cards.isLoading ? (
                <div className="space-y-3">
                  <Skeleton className="h-36 w-full" />
                  <Skeleton className="h-36 w-full" />
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
                  icon={Inbox}
                  title="Inbox zero"
                  description="No pending cards. Open an issue on an installed repo and it'll show up here within ~90 seconds."
                  action={
                    <Link
                      href="/history"
                      className="text-sm font-medium text-primary underline-offset-4 hover:underline"
                    >
                      View past decisions →
                    </Link>
                  }
                />
              )}
            </section>
          </div>
        </>
      )}
    </AppShell>
  );
}

function RepoList({ loading, repos }: { loading: boolean; repos: Repo[] }) {
  return (
    <div className="rounded-lg border bg-card p-4 shadow-sm">
      <div className="mb-3 flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        <GitBranch className="h-3.5 w-3.5" />
        Installed repos
      </div>
      {loading ? (
        <div className="space-y-2">
          <Skeleton className="h-5 w-3/4" />
          <Skeleton className="h-5 w-1/2" />
        </div>
      ) : repos && repos.length > 0 ? (
        <ul className="space-y-2 text-sm">
          {repos.map((r) => (
            <li key={r.id} className="flex items-center justify-between gap-2">
              <span className="truncate font-medium">{r.full_name}</span>
              <span className="shrink-0 text-xs text-muted-foreground">{r.indexing_status}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">
          No repos yet. Install the App from{" "}
          <Link href="/onboarding" className="underline underline-offset-4">
            onboarding
          </Link>
          .
        </p>
      )}
    </div>
  );
}

function StuckCardsBanner({ count, ids }: { count: number; ids: number[] }) {
  const rerun = useRerunCard();
  return (
    <div className="mb-6 flex items-center gap-3 rounded-lg border border-amber-500/40 bg-amber-500/10 p-4">
      <RefreshCw className="h-5 w-5 shrink-0 text-amber-700" />
      <div className="flex-1 text-sm">
        <div className="font-medium text-amber-900">
          {count} card{count === 1 ? "" : "s"} never got classified
        </div>
        <div className="text-amber-800/80">
          Usually means no LLM key was configured when the issue arrived. Now
          that your key is set, you can retry all of them at once.
        </div>
      </div>
      <Button
        size="sm"
        variant="outline"
        onClick={async () => {
          for (const id of ids) {
            await rerun.mutateAsync(id);
          }
        }}
        disabled={rerun.isPending}
      >
        {rerun.isPending ? "re-running…" : `Retry ${count}`}
      </Button>
    </div>
  );
}

function OnboardingBanner() {
  return (
    <div className="mb-6 flex items-center gap-3 rounded-lg border border-primary/30 bg-primary/5 p-4">
      <Rocket className="h-5 w-5 shrink-0 text-primary" />
      <div className="flex-1 text-sm">
        <div className="font-medium">Finish setup to start triaging</div>
        <div className="text-muted-foreground">
          Register your GitHub App and install it on a repo — takes about two minutes.
        </div>
      </div>
      <Link
        href="/onboarding"
        className="inline-flex h-9 shrink-0 items-center gap-1 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90"
      >
        Continue <ArrowRight className="h-3.5 w-3.5" />
      </Link>
    </div>
  );
}

function SignedOutHero({ appConfigured }: { appConfigured: boolean }) {
  // First-run operator needs to set up the GitHub App before OAuth login
  // is even possible. Route them to /onboarding. Once the App is in place,
  // subsequent visitors see the normal "Sign in with GitHub" CTA.
  return (
    <div className="mx-auto max-w-2xl py-24 text-center">
      <div className="mb-6 inline-flex items-center gap-2 rounded-full border bg-card px-3 py-1 text-xs font-medium text-muted-foreground">
        <span className="h-1.5 w-1.5 rounded-full bg-primary" />
        For open-source maintainers
      </div>
      <h1 className="text-5xl font-semibold tracking-tight">
        Sift signal from noise in your issue tracker.
      </h1>
      <p className="mt-5 text-lg text-muted-foreground">
        bugsift classifies, deduplicates, reproduces, and routes every incoming
        issue so your attention goes only to the ones that need it.
      </p>
      <div className="mt-8 flex items-center justify-center gap-3">
        {appConfigured ? (
          <a
            href={`${API_BASE_URL}/auth/github/start`}
            className="inline-flex h-11 items-center gap-2 rounded-md bg-primary px-6 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            Sign in with GitHub <ArrowRight className="h-4 w-4" />
          </a>
        ) : (
          <Link
            href="/onboarding"
            className="inline-flex h-11 items-center gap-2 rounded-md bg-primary px-6 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            Get started <ArrowRight className="h-4 w-4" />
          </Link>
        )}
        <a
          href={`${API_BASE_URL}/health`}
          className="inline-flex h-11 items-center rounded-md border border-input bg-background px-6 text-sm font-medium hover:bg-accent hover:text-accent-foreground"
        >
          Check backend
        </a>
      </div>
      {!appConfigured && (
        <p className="mt-4 text-xs text-muted-foreground">
          First run? Setup takes ~2 minutes and doesn&apos;t touch .env.
        </p>
      )}
      <div className="mt-16 grid gap-4 text-left sm:grid-cols-3">
        {[
          { title: "Classify", copy: "bug / feature / question / docs / spam / other with confidence." },
          { title: "Dedup + retrieve", copy: "Cosine search + LLM judge over past issues and your code." },
          { title: "Reproduce + draft", copy: "Hardened Docker sandbox runs minimal repro, then drafts the comment." },
        ].map((f) => (
          <div key={f.title} className="rounded-lg border bg-card p-4">
            <div className="text-sm font-medium">{f.title}</div>
            <div className="mt-1 text-sm text-muted-foreground">{f.copy}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
