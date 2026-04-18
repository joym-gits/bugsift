import { Button } from "@/components/ui/button";

export default function DashboardPage() {
  return (
    <main className="container mx-auto flex min-h-screen flex-col justify-center gap-6 py-16">
      <header className="space-y-2">
        <h1 className="text-4xl font-semibold tracking-tight">bugsift</h1>
        <p className="text-muted-foreground">
          Sift signal from noise in your issue tracker.
        </p>
      </header>
      <section className="rounded-lg border bg-card p-6 text-card-foreground shadow-sm">
        <h2 className="text-lg font-medium">Phase 1 — scaffolding</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          The triage pipeline is not yet implemented. This page exists to verify
          that the stack boots and that the frontend can talk to the backend.
        </p>
        <div className="mt-4 flex gap-2">
          <Button variant="default" disabled>
            No triage cards yet
          </Button>
          <a
            href="/api/health"
            className="inline-flex h-10 items-center justify-center rounded-md border border-input bg-background px-4 py-2 text-sm font-medium hover:bg-accent hover:text-accent-foreground"
          >
            Check backend
          </a>
        </div>
      </section>
    </main>
  );
}
