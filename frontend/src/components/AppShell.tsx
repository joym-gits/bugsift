"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BarChart3,
  Github,
  History,
  Inbox,
  LogOut,
  MessageSquareWarning,
  Rocket,
  ScrollText,
  Settings,
  Users as UsersIcon,
  type LucideIcon,
} from "lucide-react";

import { BugsiftLogo } from "@/components/BugsiftLogo";
import { ThemeToggle } from "@/components/ThemeToggle";
import { API_BASE_URL } from "@/lib/api";
import { type Me, useLogout } from "@/lib/hooks";
import { cn } from "@/lib/utils";

type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  adminOnly?: boolean;
};

type NavGroup = {
  label: string;
  items: NavItem[];
  adminOnly?: boolean;
};

const NAV: NavGroup[] = [
  {
    label: "Work",
    items: [
      { href: "/dashboard", label: "Queue", icon: Inbox },
      { href: "/history", label: "History", icon: History },
      { href: "/feedback", label: "Feedback apps", icon: MessageSquareWarning },
    ],
  },
  {
    label: "Configure",
    items: [
      { href: "/onboarding", label: "Onboarding", icon: Rocket },
      { href: "/github", label: "GitHub", icon: Github },
      { href: "/settings", label: "Settings", icon: Settings },
    ],
  },
  {
    label: "Admin",
    adminOnly: true,
    items: [
      { href: "/admin/metrics", label: "Metrics", icon: BarChart3 },
      { href: "/admin/users", label: "Users", icon: UsersIcon },
      { href: "/admin/audit", label: "Audit log", icon: ScrollText },
    ],
  },
];

export function AppShell({
  me,
  children,
}: {
  me: Me | null | undefined;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const logout = useLogout();

  if (!me) {
    return <SignedOutFrame>{children}</SignedOutFrame>;
  }

  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      <header className="sticky top-0 z-30 flex h-16 shrink-0 items-center justify-between gap-4 border-b bg-background/80 px-6 backdrop-blur">
        <Link href="/dashboard" className="flex items-center gap-2">
          <BugsiftLogo size="md" />
        </Link>
        <div className="flex items-center gap-1.5">
          <ThemeToggle />
          <div className="mx-1.5 h-5 w-px bg-border" aria-hidden />
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-muted text-[11px] font-semibold text-muted-foreground">
            {me.github_login.slice(0, 1).toUpperCase()}
          </div>
          <div className="hidden min-w-0 pl-1 sm:block">
            <div className="flex items-center gap-1.5 truncate text-sm font-medium leading-tight">
              {me.github_login}
              <span
                className={cn(
                  "rounded-full px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide",
                  me.role === "admin"
                    ? "bg-primary/15 text-primary"
                    : me.role === "triager"
                      ? "bg-info/15 text-info"
                      : "bg-muted text-muted-foreground",
                )}
              >
                {me.role}
              </span>
            </div>
            <div className="truncate text-[11px] text-muted-foreground">
              {me.email ?? "github user"}
            </div>
          </div>
          <button
            type="button"
            onClick={() => logout.mutate()}
            className="ml-1 inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
            aria-label="Log out"
            title="Log out"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </header>

      <div className="flex flex-1">
        <aside className="hidden w-60 shrink-0 flex-col border-r bg-card/40 md:flex">
          <nav className="flex-1 overflow-y-auto px-3 py-6">
            {NAV.filter((g) => !g.adminOnly || me.role === "admin").map((group, idx) => (
              <div key={group.label} className={cn(idx > 0 && "mt-6")}>
                <div className="mb-1.5 px-3 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                  {group.label}
                </div>
                <ul className="space-y-0.5">
                  {group.items.map((item) => {
                    const active =
                      pathname === item.href ||
                      pathname?.startsWith(`${item.href}/`);
                    const Icon = item.icon;
                    return (
                      <li key={item.href}>
                        <Link
                          href={item.href}
                          className={cn(
                            "group relative flex items-center gap-2.5 rounded-md px-3 py-2 text-[14px] font-medium transition-colors",
                            active
                              ? "bg-accent text-accent-foreground"
                              : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
                          )}
                        >
                          {active && (
                            <span
                              className="absolute inset-y-1.5 left-0 w-0.5 rounded-r-full bg-primary"
                              aria-hidden
                            />
                          )}
                          <Icon
                            className={cn(
                              "h-4 w-4 shrink-0",
                              active ? "text-primary" : "",
                            )}
                            strokeWidth={2}
                          />
                          {item.label}
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
          </nav>
        </aside>

        <main className="flex-1 overflow-x-hidden">
          <div className="mx-auto max-w-6xl px-10 py-12">{children}</div>
        </main>
      </div>
    </div>
  );
}

function SignedOutFrame({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-gradient-to-b from-background via-background to-muted/40">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-8 py-5">
        <BugsiftLogo size="md" />
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <a
            href={`${API_BASE_URL}/auth/github/start`}
            className="inline-flex h-9 items-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground shadow-elev-1 transition-colors hover:bg-primary/90"
          >
            Sign in with GitHub
          </a>
        </div>
      </header>
      <div className="mx-auto max-w-5xl px-8 pb-16">{children}</div>
    </div>
  );
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
}) {
  return (
    <header className="mb-10 flex items-end justify-between gap-4">
      <div>
        <h1 className="text-[28px] font-semibold leading-tight tracking-tight">
          {title}
        </h1>
        {description && (
          <p className="mt-2 text-[15px] text-muted-foreground">{description}</p>
        )}
      </div>
      {actions && <div className="shrink-0">{actions}</div>}
    </header>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed bg-card/50 px-6 py-16 text-center">
      <div className="flex h-11 w-11 items-center justify-center rounded-full bg-accent text-accent-foreground">
        <Icon className="h-5 w-5" />
      </div>
      <h3 className="text-base font-medium">{title}</h3>
      <p className="max-w-sm text-sm text-muted-foreground">{description}</p>
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-md bg-muted", className)} />;
}
