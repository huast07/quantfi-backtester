import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { deleteHistoryDatabase, openHistory } from "@/lib/history";
import type { RunDetail } from "@/py/types";
import { savedRun } from "@/test/saved-run";

import { ResultsPage } from "./results-page";

const search = vi.hoisted(() => ({ value: "" }));
const python = vi.hoisted(() => ({ call: vi.fn() }));
const downloads = vi.hoisted(() => ({ text: vi.fn() }));

vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams(search.value) }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
vi.mock("@/py/client", () => ({ pythonClient: () => python }));
vi.mock("@/lib/download", async (original) => ({
  ...(await original<typeof import("@/lib/download")>()),
  downloadText: downloads.text,
}));
// uPlot needs a real canvas; the chart wrapper has its own browser coverage.
vi.mock("./chart", () => ({ Chart: ({ title }: { title: string }) => <figure>{title}</figure> }));

const DETAIL: RunDetail = {
  timestamps: [0, 100, 200],
  total_pnl: [0, 5, 12],
  product_pnl: { AMETHYST: 12, TELLURIUM: -3 },
  products: [
    { product: "AMETHYST", mid: [10000, 10001, 10000], pnl: [0, 5, 12], position: [0, 2, 1], fills: [] },
    { product: "TELLURIUM", mid: [500, 501, 502], pnl: [0, -1, -3], position: [0, -1, -1], fills: [] },
  ],
  logs: [
    { timestamp: 0, text: "hello" },
    { timestamp: 100, text: "buy AMETHYST" },
  ],
  logs_truncated: true,
};

beforeEach(async () => {
  await deleteHistoryDatabase();
  Element.prototype.scrollIntoView = vi.fn();
  python.call.mockImplementation(async (method: string) => {
    if (method === "drill") return DETAIL;
    if (method === "visualizer_log") return "log text";
    if (method === "case_csv") return { day: 1, prices: "p", trades: "t" };
    throw new Error(`unexpected ${method}`);
  });
});

afterEach(() => {
  vi.clearAllMocks();
});

async function showSaved() {
  const run = savedRun();
  await (await openHistory()).save(run);
  search.value = `id=${run.id}`;
  render(<ResultsPage />);
  await screen.findByRole("heading", { name: "Results" });
  return run;
}

describe("ResultsPage", () => {
  test("asks for a run when the link has no id", () => {
    search.value = "";
    render(<ResultsPage />);
    expect(screen.getByRole("heading", { name: "No run selected" })).toBeInTheDocument();
  });

  test("explains that results stay in the browser that ran them", async () => {
    search.value = "id=missing";
    render(<ResultsPage />);
    expect(await screen.findByRole("heading", { name: "Run not found" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "History" })).toHaveAttribute("href", "/history");
  });

  test("shows every view of a saved run and exports it", async () => {
    // Arrange
    const run = await showSaved();

    // Act
    fireEvent.click(screen.getByRole("button", { name: "Export JSON" }));
    fireEvent.click(screen.getByRole("button", { name: "Text report" }));

    // Assert
    for (const name of ["Profiles", "Strategy by case", "Head to head", "Products", "Replay"]) {
      expect(screen.getByRole("heading", { level: 2, name })).toBeInTheDocument();
    }
    expect(screen.getByText("custom suite, 5 cases x 2 seeds")).toBeInTheDocument();
    expect(downloads.text).toHaveBeenCalledWith(
      "quantgen-run-2026-10-27-12-00.json",
      expect.stringContaining(run.id),
      "application/json",
    );
    expect(downloads.text).toHaveBeenCalledWith("quantgen-report-2026-10-27-12-00.txt", run.report.text);
  });

  test("replays the selected cell with charts, logs and downloads", async () => {
    // Arrange
    await showSaved();
    const replay = screen.getByRole("heading", { level: 2, name: "Replay" }).closest("section") as HTMLElement;

    // Act
    fireEvent.click(screen.getByRole("button", { name: /^amethyst_mm\.py on Busy day/ }));
    await within(replay).findByText("AMETHYST mid price and fills");

    // Assert
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
    expect(within(replay).getByRole("heading", { level: 3 })).toHaveTextContent("amethyst_mm.py on Busy day");
    expect(python.call).toHaveBeenLastCalledWith(
      "drill",
      expect.objectContaining({ case_id: "busy-day", seed: 1, match_mode: "all" }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(within(replay).getByText(/more than the browser keeps/)).toBeInTheDocument();

    fireEvent.change(within(replay).getByLabelText("Filter log lines"), { target: { value: "buy" } });
    expect(within(replay).queryByText("hello")).not.toBeInTheDocument();
    expect(within(replay).getByText("buy AMETHYST")).toBeInTheDocument();

    fireEvent.change(within(replay).getByRole("combobox"), { target: { value: "TELLURIUM" } });
    expect(within(replay).getByText("TELLURIUM position")).toBeInTheDocument();

    fireEvent.click(within(replay).getByRole("button", { name: /Seed 2/ }));
    await waitFor(() =>
      expect(python.call).toHaveBeenLastCalledWith("drill", expect.objectContaining({ seed: 2 }), expect.anything()),
    );

    fireEvent.click(within(replay).getByRole("button", { name: "Download visualizer log" }));
    await waitFor(() => expect(downloads.text).toHaveBeenCalledWith("amethyst_mm-busy-day-seed2.log", "log text"));
    fireEvent.click(within(replay).getByRole("button", { name: "Download day CSVs" }));
    await waitFor(() =>
      expect(downloads.text).toHaveBeenCalledWith("busy-day_seed2_trades_round_1_day_1.csv", "t", "text/csv"),
    );
  });

  test("explains why the reference cannot be replayed and reports replay failures", async () => {
    // Arrange
    python.call.mockRejectedValue(new Error("SyntaxError: bad strategy"));
    await showSaved();
    const replay = screen.getByRole("heading", { level: 2, name: "Replay" }).closest("section") as HTMLElement;

    // Act and assert
    expect(await within(replay).findByText(/Could not replay this day: SyntaxError/)).toBeInTheDocument();
    fireEvent.click(within(replay).getByRole("button", { name: "Download day CSVs" }));
    expect(await within(replay).findByText("SyntaxError: bad strategy")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^reference on Busy day/ }));
    expect(within(replay).getByText(/reference strategy is built into the backtester/)).toBeInTheDocument();
    expect(within(replay).queryByRole("button", { name: "Download visualizer log" })).not.toBeInTheDocument();
  });
});
