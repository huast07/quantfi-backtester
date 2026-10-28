import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { namedSuite } from "@/lib/catalog";
import { deleteHistoryDatabase, openHistory } from "@/lib/history";
import type { CallOptions } from "@/worker/pool";
import { abortError } from "@/worker/pool";
import { fixture } from "@/test/fixture";

import { BacktestPage } from "./backtest-page";

const router = vi.hoisted(() => ({ push: vi.fn() }));
const python = vi.hoisted(() => ({
  call: vi.fn(),
  pool: { warm: vi.fn(), subscribe: vi.fn(() => () => {}) },
}));

vi.mock("next/navigation", () => ({ useRouter: () => router }));
vi.mock("@/py/client", () => ({ pythonClient: () => python }));

const AMETHYST = fixture.strategies[0];
const FADES = fixture.strategies[1];

/** One case's runs from the fixture, relabelled for whichever case and seed was asked for. */
function runsFor(caseId: string, seed: number) {
  return fixture.runs
    .filter((run) => run.case_id === "regular-day" && run.seed === 1)
    .map((run) => ({ ...run, case_id: caseId, seed }));
}

function answer(method: string, payload: { case_id: string; seed: number }) {
  if (method === "check_strategy") return { ok: true, error: null };
  if (method === "run_case") return runsFor(payload.case_id, payload.seed);
  if (method === "report") return fixture.report;
  throw new Error(`unexpected ${method}`);
}

function upload(...files: Array<{ name: string; source: string }>) {
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, { target: { files: files.map((f) => new File([f.source], f.name)) } });
}

const runButton = () => screen.getByRole("button", { name: "Run backtest" });

beforeEach(async () => {
  await deleteHistoryDatabase();
  python.call.mockImplementation(async (method: string, payload: { case_id: string; seed: number }) =>
    answer(method, payload),
  );
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("BacktestPage", () => {
  test("checks uploads, runs the quick suite, saves the run and opens its results", async () => {
    // Arrange
    render(<BacktestPage />);
    expect(python.pool.warm).toHaveBeenCalledWith(1);
    expect(runButton()).toBeDisabled();
    upload(AMETHYST, FADES);
    await waitFor(() => expect(screen.getAllByText("Ready")).toHaveLength(2));

    // Act
    fireEvent.click(screen.getByRole("radio", { name: /Quick/ }));
    fireEvent.click(screen.getByRole("radio", { name: "Worse" }));
    fireEvent.click(runButton());

    // Assert
    await waitFor(() => expect(router.push).toHaveBeenCalled());
    const [saved] = await (await openHistory()).list();
    expect(router.push).toHaveBeenCalledWith(`/results?id=${saved.id}`);
    expect(saved).toMatchObject({ suiteName: "quick", matchMode: "worse", cases: namedSuite("quick").case_ids.length });
    const runCalls = python.call.mock.calls.filter(([method]) => method === "run_case");
    expect(runCalls).toHaveLength(namedSuite("quick").case_ids.length);
    expect(runCalls[0][1]).toMatchObject({ match_mode: "worse", reference: true });
  });

  test("shows why a file cannot run and keeps the run button off", async () => {
    // Arrange
    python.call.mockImplementation(async (method: string) =>
      method === "check_strategy" ? { ok: false, error: "SyntaxError: invalid syntax (line 3)" } : null,
    );
    render(<BacktestPage />);

    // Act
    upload(AMETHYST, { name: "notes.txt", source: "hello" });

    // Assert
    expect(await screen.findByText("Needs a fix")).toBeInTheDocument();
    expect(screen.getByText("SyntaxError: invalid syntax (line 3)")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("notes.txt");
    expect(runButton()).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: `Remove ${AMETHYST.name}` }));
    expect(screen.getByText("Add at least one strategy file to run.")).toBeInTheDocument();
  });

  test("builds a custom suite from chosen cases and a clamped seed count", async () => {
    // Arrange
    render(<BacktestPage />);
    upload(AMETHYST);
    await screen.findByText("Ready");

    // Act
    fireEvent.click(screen.getByRole("radio", { name: /Custom/ }));
    const stress = screen.getByRole("group", { name: /Stress/ });
    fireEvent.click(within(stress).getByRole("button", { name: "All" }));
    expect(
      within(stress)
        .getAllByRole("checkbox")
        .every((box) => (box as HTMLInputElement).checked),
    ).toBe(true);
    for (const box of screen.getAllByRole("checkbox", { checked: true })) fireEvent.click(box);

    // Assert
    expect(screen.getByText("Pick at least one case.")).toBeInTheDocument();
    expect(runButton()).toBeDisabled();

    fireEvent.click(screen.getByRole("checkbox", { name: "Regular day" }));
    fireEvent.change(screen.getByLabelText("Seeds per case"), { target: { value: "40" } });
    expect(screen.getByLabelText("Seeds per case")).toHaveValue(10);
    expect(screen.getByText(/on 10 simulated days/)).toBeInTheDocument();
  });

  test("cancels a running suite and stops its jobs", async () => {
    // Arrange
    python.call.mockImplementation(
      (method: string, payload: { case_id: string; seed: number }, options?: CallOptions) => {
        if (method !== "run_case") return Promise.resolve(answer(method, payload));
        options?.onStart?.();
        return new Promise((_, reject) => options?.signal?.addEventListener("abort", () => reject(abortError())));
      },
    );
    render(<BacktestPage />);
    upload(AMETHYST);
    await screen.findByText("Ready");
    fireEvent.click(screen.getByRole("radio", { name: /Quick/ }));
    fireEvent.click(runButton());
    const progress = await screen.findByRole("progressbar", { name: "Days simulated" });
    expect(progress).toHaveAttribute("aria-valuenow", "0");
    expect(
      within(screen.getByRole("list", { name: "Progress per case" })).getAllByLabelText(/running$/),
    ).not.toHaveLength(0);

    // Act
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    // Assert
    expect(await screen.findByText("Run cancelled.")).toBeInTheDocument();
    expect(router.push).not.toHaveBeenCalled();
  });

  test("reports a run that fails part way", async () => {
    python.call.mockImplementation(async (method: string, payload: { case_id: string; seed: number }) => {
      if (method === "run_case") throw new Error("MemoryError");
      return answer(method, payload);
    });
    render(<BacktestPage />);
    upload(AMETHYST);
    await screen.findByText("Ready");
    fireEvent.click(screen.getByRole("radio", { name: /Quick/ }));
    fireEvent.click(runButton());
    expect(await screen.findByRole("alert")).toHaveTextContent(/The run stopped: .*MemoryError/);
  });
});
