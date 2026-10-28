import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type uPlot from "uplot";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { Chart } from "./chart";

const plots = vi.hoisted(() => ({
  created: [] as Array<{ options: uPlot.Options; destroy: () => void; setSize: unknown }>,
}));
const downloads = vi.hoisted(() => ({ blob: vi.fn() }));

vi.mock("@/lib/download", () => ({ downloadBlob: downloads.blob }));
vi.mock("uplot", () => {
  class FakePlot {
    static paths = { stepped: vi.fn(() => "stepped-path") };
    width = 600;
    ctx: CanvasRenderingContext2D;
    destroy = vi.fn();
    setSize = vi.fn();
    data: uPlot.AlignedData;
    series: uPlot.Series[];
    constructor(
      public options: uPlot.Options,
      data: uPlot.AlignedData,
    ) {
      this.data = data;
      this.series = options.series;
      const canvas = document.createElement("canvas");
      canvas.width = 1200;
      canvas.height = 440;
      this.ctx = canvas.getContext("2d") as CanvasRenderingContext2D;
      plots.created.push(this);
    }
    valToPos(value: number) {
      return value;
    }
  }
  return { default: FakePlot };
});

let resize: (() => void) | null = null;
const drawing = { moveTo: vi.fn(), lineTo: vi.fn(), fill: vi.fn(), fillText: vi.fn(), drawImage: vi.fn() };

beforeEach(() => {
  plots.created = [];
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(callback: () => void) {
        resize = callback;
      }
      observe() {}
      disconnect() {}
    },
  );
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(function (this: HTMLCanvasElement) {
    return {
      canvas: this,
      ...drawing,
      save: vi.fn(),
      restore: vi.fn(),
      beginPath: vi.fn(),
      closePath: vi.fn(),
      fillRect: vi.fn(),
    } as unknown as CanvasRenderingContext2D;
  });
  vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation(function (callback: BlobCallback) {
    callback(new Blob(["png"], { type: "image/png" }));
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const DATA: uPlot.AlignedData = [
  [0, 100, 200],
  [10, 11, 12],
  [null, 11, null],
];

describe("Chart", () => {
  test("builds a line, a stepped and a marker series with formatted values", async () => {
    // Arrange and act
    const { unmount } = render(
      <Chart
        title="Price"
        exportName="run-price"
        series={[
          { label: "Mid", color: "--chart-1" },
          { label: "Bought", color: "--chart-buy", kind: "points", marker: "up" },
        ]}
        data={DATA}
        formatValue={(v) => `$${v}`}
        syncKey="drill"
      />,
    );
    await waitFor(() => expect(plots.created).toHaveLength(1));
    const [plot] = plots.created;
    const [, mid, bought] = plot.options.series;

    // Assert
    expect(plot.options.cursor?.sync?.key).toBe("drill");
    expect(mid.label).toBe("Mid");
    expect(mid.paths).toBeUndefined();
    expect((mid.value as (u: unknown, v: number | null) => string)(null, 12)).toBe("$12");
    expect((mid.value as (u: unknown, v: number | null) => string)(null, null)).toBe("-");
    expect(bought.width).toBe(0);
    (bought.points?.show as (u: unknown, i: number) => void)(plot, 2);
    expect(drawing.fill).toHaveBeenCalledTimes(1);
    const axisValues = plot.options.axes?.[1].values as (u: unknown, ticks: number[]) => string[];
    expect(axisValues(null, [1, 2])).toEqual(["$1", "$2"]);

    act(() => resize?.());
    expect(plot.setSize).toHaveBeenCalled();
    unmount();
    expect(plot.destroy).toHaveBeenCalled();
  });

  test("draws stepped series and sell markers pointing down", async () => {
    render(
      <Chart
        title="Position"
        exportName="run-position"
        series={[
          { label: "Position", color: "--chart-2", kind: "step" },
          { label: "Sold", color: "--chart-sell", kind: "points", marker: "down" },
        ]}
        data={DATA}
      />,
    );
    await waitFor(() => expect(plots.created).toHaveLength(1));
    const [plot] = plots.created;
    expect(plot.options.series[1].paths).toBe("stepped-path");
    (plot.options.series[2].points?.show as (u: unknown, i: number) => void)(plot, 2);
    expect(drawing.moveTo).toHaveBeenCalledWith(100, 11 + 7 * devicePixelRatio);
  });

  test("saves the chart with its title as a PNG", async () => {
    render(
      <Chart
        title="Profit and loss"
        exportName="run-pnl"
        series={[{ label: "PnL", color: "--chart-1" }]}
        data={DATA}
      />,
    );
    await waitFor(() => expect(plots.created).toHaveLength(1));

    fireEvent.click(screen.getByRole("button", { name: "Save PNG" }));

    await waitFor(() => expect(downloads.blob).toHaveBeenCalledWith("run-pnl.png", expect.any(Blob)));
    expect(drawing.fillText).toHaveBeenCalledWith("Profit and loss", expect.any(Number), expect.any(Number));
    expect(drawing.drawImage).toHaveBeenCalled();
  });
});
