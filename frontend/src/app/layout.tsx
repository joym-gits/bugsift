import type { Metadata } from "next";
import { GeistMono } from "geist/font/mono";
import { Inter } from "next/font/google";
import { headers } from "next/headers";
import "./globals.css";
import { Providers } from "./providers";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

export const metadata: Metadata = {
  title: "bugsift",
  description: "Sift signal from noise in your issue tracker.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  // Middleware (src/middleware.ts) stamps a per-request nonce and
  // sets the matching CSP header. Pull it off the request so
  // next-themes' pre-hydration script can carry the same nonce.
  const nonce = headers().get("x-nonce") ?? undefined;
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${inter.variable} ${GeistMono.variable}`}
    >
      <body className="min-h-screen bg-background font-sans text-foreground antialiased">
        <Providers nonce={nonce}>{children}</Providers>
      </body>
    </html>
  );
}
