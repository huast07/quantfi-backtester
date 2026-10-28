import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { formatPnl } from "@/lib/format";
import { deleteHistoryDatabase, exportRuns, openHistory } from "@/lib/history";
import { savedRun } from "@/test/saved-run";

import { HistoryPage } from "./history-page";

const downloads = vi.hoisted(() => ({ text: vi.fn() }));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
vi.mock("@/lib/download", () => ({ downloadText: downloads.text }));

beforeEach(async () => {
  await deleteHistoryDatabase();
});

afterEach(() => {
  vi.restoreAllMocks();
  downloads.text.mockReset();
});

const importInput = () => document.querySelector('input[type="file"]') as HTMLInputElement;

describe("HistoryPage", () => {
  test("invites a first run when nothing is saved", async () => {
    render(<HistoryPage />);
    expect(await screen.findByText("No saved runs yet.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Export all" })).toBeDisabled();
  });

  test("lists saved runs with their scores and links to their results", async () => {
    // Arrange
    const run = savedRun();
    await (await openHistory()).save(run);

    // Act
    render(<HistoryPage />);

    // Assert
    const link = await screen.findByRole("link", { name: "amethyst_mm.py vs fades.py" });
    expect(link).toHaveAttribute("href", `/results?id=${run.id}`);
    expect(screen.getByText("custom suite, 5 cases x 2 seeds")).toBeInTheDocument();
    expect(screen.getByText(formatPnl(run.report.overall["fades.py"].weighted_pnl))).toBeInTheDocument();
  });

  test("exports everything, deletes after confirming and imports an export back", async () => {
    // Arrange
    const run = savedRun();
    await (await openHistory()).save(run);
    render(<HistoryPage />);
    await screen.findByRole("link", { name: "Open" });
    const confirm = vi.spyOn(window, "confirm");

    // Act and assert: export
    fireEvent.click(screen.getByRole("button", { name: "Export all" }));
    await waitFor(() => expect(downloads.text).toHaveBeenCalled());
    expect(downloads.text.mock.calls[0][1]).toBe(exportRuns([run]));

    // Declining the confirmation keeps the run.
    confirm.mockReturnValueOnce(false);
    fireEvent.click(screen.getByRole("button", { name: `Delete ${run.label}` }));
    expect(screen.getByRole("link", { name: "Open" })).toBeInTheDocument();

    confirm.mockReturnValueOnce(true);
    fireEvent.click(screen.getByRole("button", { name: `Delete ${run.label}` }));
    expect(await screen.findByText("No saved runs yet.")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Run deleted.");

    const file = new File([exportRuns([run])], "backup.json", { type: "application/json" });
    fireEvent.change(importInput(), { target: { files: [file] } });
    expect(await screen.findByText("Imported 1 run from backup.json.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open" })).toBeInTheDocument();
  });

  test("reports a file that is not an export", async () => {
    render(<HistoryPage />);
    await screen.findByText("No saved runs yet.");
    const file = new File(["{}"], "notes.json", { type: "application/json" });
    fireEvent.change(importInput(), { target: { files: [file] } });
    expect(await screen.findByRole("status")).toHaveTextContent(/not a/i);
  });
});
