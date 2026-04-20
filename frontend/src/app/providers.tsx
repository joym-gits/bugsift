"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { useState } from "react";

/**
 * Root providers.
 *
 * - React Query is scoped to the client tree; the single instance lives
 *   here so SSR boundaries don't share cache.
 * - next-themes controls light / dark / system with ``class`` strategy
 *   (matches our Tailwind config) and persists the choice in
 *   localStorage. ``disableTransitionOnChange`` avoids the jarring fade
 *   of every element when the theme flips.
 */
export function Providers({
  children,
  nonce,
}: {
  children: React.ReactNode;
  nonce?: string;
}) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            refetchOnWindowFocus: false,
            retry: 1,
          },
        },
      }),
  );
  return (
    <ThemeProvider
      attribute="class"
      defaultTheme="system"
      enableSystem
      disableTransitionOnChange
      nonce={nonce}
    >
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </ThemeProvider>
  );
}
