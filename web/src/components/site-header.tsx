"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import type { PoolStatus } from "@/worker/pool";

import styles from "./site.module.css";
import ui from "./ui.module.css";
import { usePoolStatus } from "./use-python";

const NAV = [
  { href: "/", label: "Backtest" },
  { href: "/cases", label: "Cases" },
  { href: "/history", label: "History" },
] as const;

function runtimeLabel(status: PoolStatus): { text: string; tone: "idle" | "busy" | "ready" | "error" } | null {
  const workers = status.idle + status.busy;
  if (status.error && workers === 0 && status.booting === 0) return { text: "Python failed to start", tone: "error" };
  if (status.busy > 0) return { text: `Running on ${status.busy} of ${status.size} workers`, tone: "busy" };
  if (status.booting > 0 && workers === 0) return { text: "Starting Python", tone: "busy" };
  if (workers > 0) return { text: "Python ready", tone: "ready" };
  return null;
}

function RuntimeStatus() {
  const status = usePoolStatus();
  const label = status && runtimeLabel(status);
  if (!label) return null;
  return (
    <span className={`${styles.runtime} ${styles[label.tone]}`} role="status" title={status?.error ?? undefined}>
      <span className={styles.dot} aria-hidden />
      {label.text}
    </span>
  );
}

export function SiteHeader() {
  const pathname = usePathname();
  return (
    <header className={styles.header}>
      <div className={`${ui.container} ${styles.headerInner}`}>
        <Link href="/" className={styles.brand}>
          <span className={styles.mark} aria-hidden>
            Q
          </span>
          QuantiFi Backtester
        </Link>
        <nav className={styles.nav} aria-label="Main">
          {NAV.map((item) => {
            const active =
              item.href === "/" ? pathname === "/" || pathname === "/results" : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={styles.navLink}
                aria-current={active ? "page" : undefined}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
        <RuntimeStatus />
      </div>
    </header>
  );
}
