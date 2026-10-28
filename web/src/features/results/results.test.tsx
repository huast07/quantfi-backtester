import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";

import { catalog } from "@/lib/catalog";
import { formatPnl } from "@/lib/format";
import { tierWeighted } from "@/lib/scoring";
import { fixture } from "@/test/fixture";

import { CaseMatrix } from "./case-matrix";
import { HeadToHead } from "./head-to-head";
import { ProductBreakdown } from "./product-breakdown";
import { ProfileCards } from "./profile-cards";
import { WeightsControl } from "./weights-control";

const { report, suite } = fixture;
const strategies = ["amethyst_mm.py", "fades.py"];
const cases = fixture.catalog;

const columnNames = () => [...document.querySelectorAll("thead th")].map((th) => th.textContent);
const sideTitles = () => screen.getAllByRole("heading", { level: 4 }).map((h) => h.textContent);

let onSelect: ReturnType<typeof vi.fn<(strategy: string, caseId: string) => void>>;

beforeEach(() => {
  onSelect = vi.fn();
});

describe("WeightsControl", () => {
  test("shows each present tier's share and reports a changed weight", () => {
    // Arrange
    const onChange = vi.fn();
    render(<WeightsControl weights={catalog.tier_weights} tiersPresent={["observed", "stress"]} onChange={onChange} />);

    // Act
    fireEvent.change(screen.getByRole("slider", { name: /Stress/ }), { target: { value: "40" } });

    // Assert
    expect(screen.getByRole("slider", { name: /Plausible/ })).toBeDisabled();
    expect(screen.getByRole("slider", { name: /Observed/ })).toHaveAttribute("aria-valuetext", "86%");
    expect(onChange).toHaveBeenCalledWith({ ...catalog.tier_weights, stress: 0.4 });
    expect(screen.getByRole("button", { name: "Reset" })).toBeDisabled();
  });

  test("never lets every present tier drop to zero", () => {
    const onChange = vi.fn();
    render(
      <WeightsControl
        weights={{ observed: 0, plausible: 0.3, stress: 0.1 }}
        tiersPresent={["observed", "stress"]}
        onChange={onChange}
      />,
    );
    fireEvent.change(screen.getByRole("slider", { name: /Stress/ }), { target: { value: "0" } });
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    expect(onChange).toHaveBeenCalledWith(catalog.tier_weights);
  });
});

describe("ProfileCards", () => {
  test("lists where each strategy does well and badly and opens a case on click", () => {
    // Arrange
    render(
      <ProfileCards
        strategies={strategies}
        report={report}
        cases={cases}
        weights={catalog.tier_weights}
        onSelect={onSelect}
      />,
    );
    const [amethyst, fades] = screen.getAllByRole("article");

    // Act
    fireEvent.click(within(amethyst).getByRole("button", { name: /Busy day/ }));

    // Assert
    expect(within(amethyst).getByText(formatPnl(report.overall["amethyst_mm.py"].weighted_pnl))).toBeInTheDocument();
    expect(within(fades).getByText("No case stands out as strong.")).toBeInTheDocument();
    expect(onSelect).toHaveBeenCalledWith("amethyst_mm.py", "busy-day");
  });

  test("collapses long lists behind a show-all toggle", () => {
    render(
      <ProfileCards
        strategies={["fades.py"]}
        report={report}
        cases={cases}
        weights={catalog.tier_weights}
        onSelect={onSelect}
      />,
    );
    const poorly = screen.getByText("Performs poorly in").closest("div") as HTMLElement;
    expect(within(poorly).getAllByRole("listitem")).toHaveLength(4);
    fireEvent.click(within(poorly).getByRole("button", { name: "Show all 5" }));
    expect(within(poorly).getAllByRole("listitem")).toHaveLength(5);
    fireEvent.click(within(poorly).getByRole("button", { name: "Show fewer" }));
    expect(within(poorly).getAllByRole("listitem")).toHaveLength(4);
  });
});

describe("CaseMatrix", () => {
  test("shows every strategy and the reference by case and selects a cell", () => {
    // Arrange
    render(
      <CaseMatrix
        strategies={strategies}
        reference={catalog.reference}
        report={report}
        caseIds={suite.case_ids}
        weights={catalog.tier_weights}
        selected={{ strategy: "fades.py", caseId: "busy-day" }}
        onSelect={onSelect}
      />,
    );
    const cell = screen.getByRole("button", { name: /^amethyst_mm\.py on Black swan crash/ });

    // Act
    fireEvent.click(cell);

    // Assert
    expect(columnNames()).toEqual(["Case", "amethyst_mm.py", "fades.py", "reference"]);
    expect(cell).toHaveAccessibleName(/strong$/);
    expect(screen.getByRole("button", { name: /^fades\.py on Busy day/ })).toHaveAttribute("aria-pressed", "true");
    expect(onSelect).toHaveBeenCalledWith("amethyst_mm.py", "black-swan-crash");
    const footer = screen.getByRole("row", { name: /Weighted score/ });
    expect(footer).toHaveTextContent(formatPnl(tierWeighted(report.stats.reference, catalog.tier_weights)));
  });
});

describe("HeadToHead", () => {
  test("splits the cases by which strategy was ahead and swaps sides", () => {
    // Arrange
    render(<HeadToHead strategies={strategies} report={report} onSelect={onSelect} />);
    const [first, second] = screen.getAllByRole("combobox");

    // Act
    fireEvent.click(screen.getAllByRole("button", { name: /Regular day/ })[0]);

    // Assert
    expect(screen.getByText(/Never ahead of/)).toHaveTextContent("Never ahead of amethyst_mm.py.");
    expect(onSelect).toHaveBeenCalledWith("amethyst_mm.py", "regular-day");
    expect(within(second).getByRole("option", { name: "amethyst_mm.py" })).toBeDisabled();

    expect(sideTitles()).toEqual(["amethyst_mm.py ahead 5", "fades.py ahead 0"]);

    fireEvent.change(first, { target: { value: "fades.py" } });
    fireEvent.change(second, { target: { value: "amethyst_mm.py" } });
    expect(sideTitles()).toEqual(["fades.py ahead 0", "amethyst_mm.py ahead 5"]);
  });
});

describe("ProductBreakdown", () => {
  test("shows the traded products per case and the breadth for the chosen strategy", () => {
    // Arrange
    render(<ProductBreakdown strategies={strategies} report={report} productCount={26} />);

    // Act
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "fades.py" } });

    // Assert
    expect(columnNames()).toEqual(["Case", "TELLURIUM"]);
    expect(screen.getByText(/made or lost money on/)).toHaveTextContent("1 of 26 products");
    expect(screen.getByRole("row", { name: /Mean over cases/ })).toBeInTheDocument();
  });

  test("says so when a strategy never traded", () => {
    const idle = {
      ...report,
      stats: {
        ...report.stats,
        "fades.py": report.stats["fades.py"].map((s) => ({
          ...s,
          product_mean_pnl: Object.fromEntries(Object.keys(s.product_mean_pnl).map((p) => [p, 0])),
        })),
      },
    };
    render(<ProductBreakdown strategies={["fades.py"]} report={idle} productCount={26} />);
    expect(screen.getByText("This strategy did not trade.")).toBeInTheDocument();
  });
});
