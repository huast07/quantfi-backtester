// Shapes one run's per-tick traces into chart series: price with fill markers, position, and PnL.
import type { RunDetail } from "@/py/types";

type Column = Array<number | null>;

export interface DrillSeries {
  /** [timestamps, mid, buy price, sell price]; the fill columns are null on ticks without fills. */
  price: [number[], Column, Column, Column];
  position: [number[], Column];
  /** [timestamps, product PnL, total PnL]. */
  pnl: [number[], Column, Column];
  bought: number;
  sold: number;
}

/** Volume-weighted price of the fills on each tick, by side. */
function fillColumn(timestamps: number[], fills: RunDetail["products"][number]["fills"], side: 1 | -1): Column {
  const totals = new Map<number, { value: number; quantity: number }>();
  for (const fill of fills) {
    if (Math.sign(fill.quantity) !== side) continue;
    const lots = Math.abs(fill.quantity);
    const current = totals.get(fill.timestamp) ?? { value: 0, quantity: 0 };
    totals.set(fill.timestamp, { value: current.value + fill.price * lots, quantity: current.quantity + lots });
  }
  return timestamps.map((t) => {
    const total = totals.get(t);
    return total ? total.value / total.quantity : null;
  });
}

export function drillSeries(detail: RunDetail, product: string): DrillSeries {
  const trace = detail.products.find((p) => p.product === product);
  if (!trace) throw new Error(`No trace for ${product} in this run`);
  const x = detail.timestamps;
  const lots = (side: 1 | -1) =>
    trace.fills.filter((f) => Math.sign(f.quantity) === side).reduce((sum, f) => sum + Math.abs(f.quantity), 0);
  return {
    price: [x, trace.mid, fillColumn(x, trace.fills, 1), fillColumn(x, trace.fills, -1)],
    position: [x, trace.position],
    pnl: [x, trace.pnl, detail.total_pnl],
    bought: lots(1),
    sold: lots(-1),
  };
}

export function defaultProduct(detail: RunDetail): string | null {
  const ranked = detail.products.toSorted(
    (a, b) => Math.abs(detail.product_pnl[b.product] ?? 0) - Math.abs(detail.product_pnl[a.product] ?? 0),
  );
  return ranked[0]?.product ?? null;
}
