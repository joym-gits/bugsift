"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Client-side Mermaid renderer.
 *
 * The mermaid library is big (~700KB) and runs only in the browser, so
 * we dynamic-import it on mount. Each diagram gets a stable id derived
 * from the source hash so two cards with the same src don't fight over
 * the same DOM node.
 *
 * If Mermaid can't parse the source (LLMs produce invalid syntax from
 * time to time) we fall back to rendering the raw source in a `<pre>`
 * block instead of throwing.
 */
export function Mermaid({ source }: { source: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [svg, setSvg] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (!source.trim()) return;
    (async () => {
      try {
        const mermaid = (await import("mermaid")).default;
        mermaid.initialize({
          startOnLoad: false,
          theme: "neutral",
          securityLevel: "strict",
        });
        const id = `m${hash(source)}`;
        const { svg } = await mermaid.render(id, source);
        if (!cancelled) {
          setSvg(svg);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "mermaid parse failed");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [source]);

  if (error) {
    return (
      <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-xs">
        <div className="font-medium text-destructive">
          Mermaid failed to render
        </div>
        <pre className="mt-2 whitespace-pre-wrap font-mono text-[11px]">
          {source}
        </pre>
      </div>
    );
  }

  if (svg === null) {
    return (
      <div className="h-40 animate-pulse rounded-md border bg-muted/20" />
    );
  }

  return (
    <div
      ref={ref}
      className="overflow-auto rounded-md border bg-background p-4"
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}

function hash(s: string): string {
  let h = 0;
  for (let i = 0; i < s.length; i++) {
    h = (h << 5) - h + s.charCodeAt(i);
    h |= 0;
  }
  return Math.abs(h).toString(36);
}
