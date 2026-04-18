"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { API_BASE_URL, ApiError } from "@/lib/api";
import {
  type ApiKey,
  useCreateKey,
  useDeleteKey,
  useKeys,
  useMe,
} from "@/lib/hooks";

const PROVIDERS: ApiKey["provider"][] = ["anthropic", "openai", "google", "ollama"];

export default function SettingsPage() {
  const me = useMe();
  const keys = useKeys(Boolean(me.data));
  const createKey = useCreateKey();
  const deleteKey = useDeleteKey();

  const [provider, setProvider] = useState<ApiKey["provider"]>("anthropic");
  const [keyValue, setKeyValue] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  if (me.isLoading) {
    return (
      <main className="container mx-auto py-16 text-muted-foreground">loading…</main>
    );
  }

  if (!me.data) {
    return (
      <main className="container mx-auto flex min-h-screen flex-col justify-center gap-6 py-16">
        <h1 className="text-3xl font-semibold tracking-tight">Settings</h1>
        <p className="text-muted-foreground">
          Sign in with GitHub to manage your API keys and repo settings.
        </p>
        <a
          href={`${API_BASE_URL}/auth/github/start`}
          className="inline-flex h-10 w-fit items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          Sign in with GitHub
        </a>
      </main>
    );
  }

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);
    if (!keyValue.trim()) {
      setFormError("paste the api key before saving");
      return;
    }
    try {
      await createKey.mutateAsync({ provider, key: keyValue.trim() });
      setKeyValue("");
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "failed to save key");
    }
  };

  return (
    <main className="container mx-auto flex flex-col gap-8 py-16">
      <header className="space-y-2">
        <h1 className="text-3xl font-semibold tracking-tight">Settings</h1>
        <p className="text-muted-foreground">
          Signed in as <strong>{me.data.github_login}</strong>. API keys are encrypted
          at rest with Fernet and never returned in plaintext.
        </p>
      </header>

      <section className="rounded-lg border bg-card p-6 shadow-sm">
        <h2 className="text-lg font-medium">Add an LLM API key</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Saving a new key for a provider replaces the previous one.
        </p>
        <form className="mt-4 grid gap-4 sm:grid-cols-[180px_1fr_auto]" onSubmit={onSubmit}>
          <div className="space-y-1">
            <Label htmlFor="provider">Provider</Label>
            <select
              id="provider"
              value={provider}
              onChange={(e) => setProvider(e.target.value as ApiKey["provider"])}
              className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
            >
              {PROVIDERS.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="key">Key</Label>
            <Input
              id="key"
              type="password"
              autoComplete="off"
              placeholder="sk-..."
              value={keyValue}
              onChange={(e) => setKeyValue(e.target.value)}
            />
          </div>
          <div className="flex items-end">
            <Button type="submit" disabled={createKey.isPending}>
              {createKey.isPending ? "saving…" : "Save key"}
            </Button>
          </div>
        </form>
        {formError && <p className="mt-3 text-sm text-destructive">{formError}</p>}
      </section>

      <section className="rounded-lg border bg-card p-6 shadow-sm">
        <h2 className="text-lg font-medium">Stored keys</h2>
        {keys.isLoading ? (
          <p className="mt-2 text-sm text-muted-foreground">loading…</p>
        ) : keys.data && keys.data.length > 0 ? (
          <ul className="mt-4 divide-y">
            {keys.data.map((k) => (
              <li key={k.id} className="flex items-center justify-between py-3">
                <div>
                  <div className="font-medium">{k.provider}</div>
                  <div className="text-sm text-muted-foreground">{k.masked_hint}</div>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => deleteKey.mutate(k.id)}
                  disabled={deleteKey.isPending}
                >
                  Delete
                </Button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-sm text-muted-foreground">no keys saved yet.</p>
        )}
      </section>
    </main>
  );
}
