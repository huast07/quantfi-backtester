import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";

import { catalog } from "@/lib/catalog";

import { CasesPage } from "./cases-page";

const day = vi.hoisted(() => ({ download: vi.fn() }));

vi.mock("@/lib/case-day", () => ({ downloadCaseDay: day.download }));

// Cheap queries on purpose: role and label lookups walk all 42 cards, slow enough in jsdom to time out under load.
const cards = () => [...document.querySelectorAll("details")];
const filter = (name: string) => screen.getByText(name, { selector: "button" });
const search = () => screen.getByPlaceholderText("Search cases, products or authors");

describe("CasesPage", () => {
  test("lists every case grouped by tier", () => {
    render(<CasesPage />);
    expect(cards()).toHaveLength(catalog.cases.length);
    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual([
      expect.stringMatching(/^Observed/),
      expect.stringMatching(/^Plausible/),
      expect.stringMatching(/^Stress/),
    ]);
  });

  test("filters by tier and by search words across titles and references", () => {
    // Arrange
    render(<CasesPage />);

    // Act
    fireEvent.click(filter("Stress"));

    // Assert
    expect(cards()).toHaveLength(catalog.cases.filter((c) => c.tier === "stress").length);

    fireEvent.click(filter("All"));
    fireEvent.change(search(), { target: { value: "gatev 2006" } });
    expect(cards().map((card) => card.id)).toContain("basket-dislocation");

    fireEvent.change(search(), { target: { value: "no such thing" } });
    expect(screen.getByText("No case matches that search.")).toBeInTheDocument();
  });

  test("shows a case's parameters and downloads a chosen seed", async () => {
    // Arrange
    day.download.mockResolvedValueOnce(undefined).mockRejectedValueOnce(new Error("Python failed to start"));
    render(<CasesPage />);
    const card = document.getElementById("basket-dislocation") as HTMLElement;
    const seed = within(card).getByLabelText("Seed");
    const button = within(card).getByRole("button", { name: "Download day CSVs" });

    // Act
    fireEvent.change(seed, { target: { value: "0" } });

    // Assert
    expect(within(card).getByText("Seeds run from 1 to 9999.")).toBeInTheDocument();
    expect(button).toBeDisabled();
    expect(within(card).getByText("10% to 40% of the day")).toBeInTheDocument();
    expect(within(card).getByText("Gatev, Goetzmann & Rouwenhorst (2006)")).toBeInTheDocument();

    fireEvent.change(seed, { target: { value: "7" } });
    fireEvent.click(button);
    await waitFor(() => expect(day.download).toHaveBeenCalledWith("basket-dislocation", 7));
    await waitFor(() => expect(button).toBeEnabled());

    fireEvent.click(button);
    expect(await within(card).findByRole("alert")).toHaveTextContent("Python failed to start");
  });
});
