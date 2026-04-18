import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "bugsift",
  description: "Sift signal from noise in your issue tracker.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen bg-background text-foreground antialiased">{children}</body>
    </html>
  );
}
