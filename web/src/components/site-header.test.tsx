import { render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";

import type { PoolStatus } from "@/worker/pool";

import { SiteFooter } from "./site-footer";
import { SiteHeader } from "./site-header";

const state = vi.hoisted(() => ({ pathname: "/", status: null as PoolStatus | null }));

vi.mock("next/navigation", () => ({ usePathname: () => state.pathname }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
vi.mock("./use-python", () => ({ usePoolStatus: () => state.status }));

const pool = (overrides: Partial<PoolStatus>): PoolStatus => ({
  size: 3,
  booting: 0,
  idle: 0,
  busy: 0,
  error: null,
  ...overrides,
});

function renderAt(pathname: string, status: PoolStatus | null) {
  state.pathname = pathname;
  state.status = status;
  return render(<SiteHeader />);
}

describe("SiteHeader", () => {
  test("marks the current section, counting results as part of Backtest", () => {
    renderAt("/results", null);
    expect(screen.getByRole("link", { name: "Backtest" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "History" })).not.toHaveAttribute("aria-current");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  test.each([
    [pool({ booting: 1 }), "Starting Python"],
    [pool({ idle: 1 }), "Python ready"],
    [pool({ idle: 1, busy: 2 }), "Running on 2 of 3 workers"],
    [pool({ error: "Could not download pyodide.mjs" }), "Python failed to start"],
    [pool({}), null],
  ])("describes the runtime (%#)", (status, label) => {
    renderAt("/cases", status);
    expect(screen.getByRole("link", { name: "Cases" })).toHaveAttribute("aria-current", "page");
    if (label === null) {
      expect(screen.queryByRole("status")).not.toBeInTheDocument();
    } else {
      expect(screen.getByRole("status")).toHaveTextContent(label);
    }
  });

  test("shows a boot failure's reason on hover", () => {
    renderAt("/", pool({ error: "Could not download pyodide.mjs" }));
    expect(screen.getByRole("status")).toHaveAttribute("title", "Could not download pyodide.mjs");
  });
});

describe("SiteFooter", () => {
  test("says that strategies never leave the machine", () => {
    render(<SiteFooter />);
    expect(screen.getByRole("contentinfo")).toHaveTextContent(/never leave your machine/);
  });
});
