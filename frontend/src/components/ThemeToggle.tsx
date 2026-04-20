"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

import { cn } from "@/lib/utils";

const ORDER = ["system", "light", "dark"] as const;
type Mode = (typeof ORDER)[number];

const LABEL: Record<Mode, string> = {
  system: "System theme",
  light: "Light theme",
  dark: "Dark theme",
};

export function ThemeToggle({ className }: { className?: string }) {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const current = (mounted ? (theme as Mode) : "system") ?? "system";
  const next = ORDER[(ORDER.indexOf(current) + 1) % ORDER.length];

  const Icon =
    current === "light" ? Sun : current === "dark" ? Moon : Monitor;

  return (
    <button
      type="button"
      onClick={() => setTheme(next)}
      className={cn(
        "inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground",
        className,
      )}
      aria-label={`Switch to ${LABEL[next].toLowerCase()}`}
      title={LABEL[current]}
    >
      <Icon className="h-4 w-4" />
    </button>
  );
}
