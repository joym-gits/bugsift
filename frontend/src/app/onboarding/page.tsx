"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Check, Copy, ExternalLink, Rocket, KeyRound, Terminal } from "lucide-react";

import { AppShell, PageHeader } from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { API_BASE_URL, ApiError } from "@/lib/api";
import {
  type ApiKey,
  type TestKeyResult,
  useAppStatus,
  useCreateKey,
  useKeys,
  useMe,
  useRepos,
  useTestKey,
} from "@/lib/hooks";

type Step = "app" | "install" | "key";

export default function OnboardingPage() {
  return (
    <Suspense fallback={<div className="container mx-auto py-16 text-muted-foreground">loading…</div>}>
      <OnboardingInner />
    </Suspense>
  );
}

function OnboardingInner() {
  const me = useMe();
  const signedIn = Boolean(me.data);
  const searchParams = useSearchParams();
  // Status is public (no auth) — we need it *before* login in order to
  // show Step 1 to the first-run operator.
  const appStatus = useAppStatus(true);
  const keys = useKeys(signedIn);
  const repos = useRepos(signedIn);
  const appConfigured = appStatus.data?.configured ?? false;

  const currentStep = resolveStep({
    forced: searchParams?.get("step") as Step | null,
    appConfigured,
    hasRepo: (repos.data?.length ?? 0) > 0,
    hasKey: (keys.data?.length ?? 0) > 0,
  });

  // Steps 2+ need a signed-in user to link installations / persist keys.
  // Step 1 is intentionally anonymous so the first-run operator can create
  // the App before any OAuth is possible.
  const needsSignIn = currentStep !== "app" && !signedIn;

  return (
    <AppShell me={me.data ?? null}>
      <PageHeader
        title="Get set up"
        description="Three quick steps and you're triaging. No .env editing required."
      />
      <StepShell
        steps={[
          { id: "app", label: "Register App", icon: Rocket },
          { id: "install", label: "Install on repo", icon: ExternalLink },
          { id: "key", label: "Add LLM key", icon: KeyRound },
        ]}
        current={currentStep}
      />

      <div className="mt-8">
        {needsSignIn ? (
          <SignInPrompt nextStep={currentStep} />
        ) : currentStep === "app" ? (
          <AppStep
            configured={appConfigured}
            tunnelUrl={appStatus.data?.tunnel_url}
          />
        ) : currentStep === "install" ? (
          <InstallStep
            appHtmlUrl={appStatus.data?.html_url ?? null}
            hasRepo={(repos.data?.length ?? 0) > 0}
          />
        ) : (
          <KeyStep />
        )}
      </div>
    </AppShell>
  );
}

function SignInPrompt({ nextStep }: { nextStep: Step }) {
  const label =
    nextStep === "install"
      ? "Installing the App on a repo links it to your bugsift account."
      : "Your LLM key is stored against your user, encrypted at rest.";
  return (
    <section className="rounded-lg border bg-card p-8 text-center shadow-sm">
      <h2 className="text-xl font-semibold">Sign in to continue</h2>
      <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">{label}</p>
      <a
        href={`${API_BASE_URL}/auth/github/start`}
        className="mt-6 inline-flex h-10 items-center rounded-md bg-primary px-5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
      >
        Sign in with GitHub
      </a>
    </section>
  );
}

function resolveStep({
  forced,
  appConfigured,
  hasRepo,
  hasKey,
}: {
  forced: Step | null;
  appConfigured: boolean;
  hasRepo: boolean;
  hasKey: boolean;
}): Step {
  if (forced && (forced === "app" || forced === "install" || forced === "key")) return forced;
  if (!appConfigured) return "app";
  if (!hasRepo) return "install";
  if (!hasKey) return "key";
  return "key";
}

function StepShell({
  steps,
  current,
}: {
  steps: { id: Step; label: string; icon: typeof Rocket }[];
  current: Step;
}) {
  const currentIndex = steps.findIndex((s) => s.id === current);
  return (
    <ol className="flex items-center gap-3">
      {steps.map((s, i) => {
        const Icon = s.icon;
        const active = s.id === current;
        const done = i < currentIndex;
        return (
          <li key={s.id} className="flex flex-1 items-center gap-3">
            <div
              className={[
                "flex h-9 w-9 shrink-0 items-center justify-center rounded-full border text-sm font-semibold",
                done
                  ? "border-primary bg-primary text-primary-foreground"
                  : active
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-muted-foreground/30 bg-background text-muted-foreground",
              ].join(" ")}
            >
              {done ? <Check className="h-4 w-4" /> : <Icon className="h-4 w-4" />}
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Step {i + 1}
              </div>
              <div className={active ? "text-sm font-semibold" : "text-sm"}>{s.label}</div>
            </div>
            {i < steps.length - 1 && <div className="hidden h-px flex-1 bg-border sm:block" />}
          </li>
        );
      })}
    </ol>
  );
}

function AppStep({
  configured,
  tunnelUrl,
}: {
  configured: boolean;
  tunnelUrl: string | null | undefined;
}) {
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const onStart = async () => {
    setError(null);
    setSubmitting(true);
    try {
      // Backend auto-provisions a smee channel + starts the in-process
      // forwarder, then returns an HTML form that auto-submits the manifest
      // to GitHub. The operator never sees a terminal.
      const response = await fetch(`${API_BASE_URL}/github/app/manifest/start`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!response.ok) {
        const body = await response.text();
        setError(body || `request failed: ${response.status}`);
        setSubmitting(false);
        return;
      }
      const html = await response.text();
      const win = window.open("about:blank", "_self");
      if (win) {
        win.document.open();
        win.document.write(html);
        win.document.close();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to start");
      setSubmitting(false);
    }
  };

  return (
    <section className="rounded-lg border bg-card p-6 shadow-sm">
      <h2 className="text-xl font-semibold">Register your GitHub App</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        One click. bugsift hands you to GitHub with a pre-filled manifest, you
        confirm, and come back. No terminal, no &ldquo;paste this URL&rdquo;,
        no .env editing.
      </p>

      {configured ? (
        <div className="mt-5 flex items-center gap-2 rounded-md border border-primary/30 bg-primary/5 p-3 text-sm">
          <Check className="h-4 w-4 text-primary" />
          <span>Your App is already registered. Continue to the next step.</span>
        </div>
      ) : (
        <div className="mt-5 flex items-start gap-2 rounded-md border bg-muted/30 p-3 text-sm">
          <Terminal className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
          <div className="text-muted-foreground">
            <div className="font-medium text-foreground">How we route GitHub webhooks</div>
            Your localhost can&apos;t receive webhooks directly, so bugsift
            auto-provisions a free{" "}
            <a
              href="https://smee.io"
              target="_blank"
              rel="noopener noreferrer"
              className="underline underline-offset-4"
            >
              smee.io
            </a>{" "}
            channel and relays events in-process. You never see it unless
            something breaks.
            {tunnelUrl && (
              <div className="mt-1 font-mono text-xs text-foreground/60">
                tunnel: {tunnelUrl}
              </div>
            )}
          </div>
        </div>
      )}

      {error && (
        <p className="mt-3 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      )}
      <div className="mt-5 flex items-center gap-3">
        <Button size="lg" onClick={onStart} disabled={submitting || configured}>
          {submitting ? "redirecting…" : configured ? "Already registered" : "Register GitHub App"}
        </Button>
        {configured && (
          <Link href="/onboarding?step=install" className="text-sm underline underline-offset-4">
            Continue to step 2 →
          </Link>
        )}
      </div>
    </section>
  );
}

function InstallStep({
  appHtmlUrl,
  hasRepo,
}: {
  appHtmlUrl: string | null;
  hasRepo: boolean;
}) {
  return (
    <section className="rounded-lg border bg-card p-6 shadow-sm">
      <h2 className="text-xl font-semibold">Install the App on a repo</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        Pick a scratch repo for your first run — ideally one you own where
        opening test issues is fine.
      </p>

      {hasRepo ? (
        <div className="mt-5 flex items-center gap-2 rounded-md border border-primary/30 bg-primary/5 p-3 text-sm">
          <Check className="h-4 w-4 text-primary" />
          <span>You have at least one installed repo. Continue to the next step.</span>
        </div>
      ) : (
        <p className="mt-4 text-sm text-muted-foreground">
          You&apos;ll land back here after installation.
        </p>
      )}

      <div className="mt-5 flex items-center gap-3">
        {appHtmlUrl ? (
          <a
            href={appHtmlUrl + "/installations/new"}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex h-10 items-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            Install on GitHub <ExternalLink className="h-4 w-4" />
          </a>
        ) : (
          <div className="text-sm text-destructive">
            App URL unknown — complete step 1 first.
          </div>
        )}
        {hasRepo && (
          <Link href="/onboarding?step=key" className="text-sm underline underline-offset-4">
            Continue to step 3 →
          </Link>
        )}
      </div>
    </section>
  );
}

function KeyStep() {
  const createKey = useCreateKey();
  const keys = useKeys(true);
  const testKey = useTestKey();
  const [keyValue, setKeyValue] = useState("");
  const [provider, setProvider] = useState<ApiKey["provider"]>("anthropic");
  const [error, setError] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<TestKeyResult | null>(null);

  const onSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!keyValue.trim()) {
      setError("paste the api key before saving");
      return;
    }
    try {
      await createKey.mutateAsync({ provider, key: keyValue.trim() });
      setKeyValue("");
      const result = await testKey.mutateAsync(provider);
      setTestResult(result);
    } catch (err) {
      if (err instanceof ApiError) setError(err.message);
      else if (err instanceof Error) setError(err.message);
      else setError("failed to save key");
    }
  };

  const done = (keys.data?.length ?? 0) > 0 && testResult?.ok;

  return (
    <section className="rounded-lg border bg-card p-6 shadow-sm">
      <h2 className="text-xl font-semibold">Add an LLM API key</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        Anthropic is the default. Keys are Fernet-encrypted at rest. We&apos;ll
        do a test call right after saving so you know it works.
      </p>

      <form className="mt-5 grid gap-4 sm:grid-cols-[180px_1fr_auto]" onSubmit={onSave}>
        <div className="space-y-1">
          <Label htmlFor="p">Provider</Label>
          <select
            id="p"
            value={provider}
            onChange={(e) => setProvider(e.target.value as ApiKey["provider"])}
            className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
          >
            {["anthropic", "openai", "google", "ollama"].map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="k">Key</Label>
          <Input
            id="k"
            type="password"
            autoComplete="off"
            placeholder="sk-ant-api03-..."
            value={keyValue}
            onChange={(e) => setKeyValue(e.target.value)}
          />
        </div>
        <div className="flex items-end">
          <Button type="submit" disabled={createKey.isPending || testKey.isPending}>
            {createKey.isPending || testKey.isPending ? "testing…" : "Save & test"}
          </Button>
        </div>
      </form>
      {error && (
        <p className="mt-3 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      )}
      {testResult && (
        <div
          className={
            "mt-3 rounded-md px-3 py-2 text-sm " +
            (testResult.ok
              ? "bg-primary/10 text-primary"
              : "bg-destructive/10 text-destructive")
          }
        >
          {testResult.ok
            ? `✓ ${testResult.provider} · ${testResult.model} · ${testResult.latency_ms}ms`
            : `failed: ${testResult.error}`}
        </div>
      )}
      {done && (
        <div className="mt-5 flex items-center gap-3">
          <Link
            href="/dashboard"
            className="inline-flex h-10 items-center gap-2 rounded-md bg-primary px-5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            Go to your queue <Check className="h-4 w-4" />
          </Link>
        </div>
      )}
    </section>
  );
}

function CopyBlock({ command }: { command: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="mt-2 flex items-center gap-2 rounded-md border bg-background px-3 py-2 font-mono text-xs">
      <code className="flex-1 overflow-x-auto whitespace-nowrap">{command}</code>
      <button
        type="button"
        onClick={async () => {
          await navigator.clipboard.writeText(command);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        }}
        className="shrink-0 rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
        aria-label="Copy command"
      >
        {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      </button>
    </div>
  );
}

