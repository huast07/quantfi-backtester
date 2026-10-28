"use client";

import { useEffect, useRef } from "react";
import type uPlot from "uplot";

import "uplot/dist/uPlot.min.css";

import ui from "@/components/ui.module.css";
import { downloadBlob } from "@/lib/download";

import styles from "./results.module.css";

export interface ChartSeries {
  label: string;
  /** A CSS custom property name such as "--chart-1". */
  color: string;
  kind?: "line" | "step" | "points";
  /** Marker for "points" series. */
  marker?: "up" | "down";
  width?: number;
}

interface Props {
  title: string;
  /** For the PNG file name and heading. */
  exportName: string;
  series: ChartSeries[];
  /** [x, ...one array per series], equal lengths; null leaves a gap. */
  data: uPlot.AlignedData;
  height?: number;
  formatValue?: (value: number) => string;
  /** Charts sharing a key move their cursors together. */
  syncKey?: string;
}

const DEFAULT_HEIGHT = 220;
const MARKER_SIZE = 7;
/** Room for labels such as "10,000.5" or "-12,345" in the 11px mono axis font. */
const Y_AXIS_WIDTH = 84;

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** A triangle marker drawn with the series' color, pointing up for buys and down for sells. */
function triangle(direction: "up" | "down"): uPlot.Series.Points.Show {
  return (u, seriesIdx) => {
    const series = u.series[seriesIdx];
    const ctx = u.ctx;
    const [xs, ys] = [u.data[0], u.data[seriesIdx]];
    const size = MARKER_SIZE * devicePixelRatio;
    ctx.save();
    ctx.fillStyle =
      series.stroke instanceof Function ? (series.stroke(u, seriesIdx) as string) : (series.stroke as string);
    for (let i = 0; i < xs.length; i++) {
      const y = ys[i];
      if (y == null) continue;
      const cx = u.valToPos(xs[i], "x", true);
      const cy = u.valToPos(y, "y", true);
      ctx.beginPath();
      if (direction === "up") {
        ctx.moveTo(cx, cy - size);
        ctx.lineTo(cx - size * 0.8, cy + size * 0.6);
        ctx.lineTo(cx + size * 0.8, cy + size * 0.6);
      } else {
        ctx.moveTo(cx, cy + size);
        ctx.lineTo(cx - size * 0.8, cy - size * 0.6);
        ctx.lineTo(cx + size * 0.8, cy - size * 0.6);
      }
      ctx.closePath();
      ctx.fill();
    }
    ctx.restore();
    return undefined;
  };
}

function buildOptions(
  uPlotLib: typeof uPlot,
  { series, height = DEFAULT_HEIGHT, formatValue, syncKey }: Props,
  width: number,
): uPlot.Options {
  const grid = { stroke: cssVar("--chart-grid"), width: 1 };
  const axisColor = cssVar("--text-faint");
  const font = `11px ${cssVar("--font-geist-mono") || "monospace"}`;
  const valueFormat = formatValue ?? ((v: number) => String(v));
  return {
    width,
    height,
    cursor: { sync: syncKey ? { key: syncKey } : undefined, points: { size: 6 } },
    legend: { live: true },
    scales: { x: { time: false } },
    axes: [
      { stroke: axisColor, grid, ticks: grid, font, values: (_, ticks) => ticks.map((t) => String(t)) },
      { stroke: axisColor, grid, ticks: grid, font, size: Y_AXIS_WIDTH, values: (_, ticks) => ticks.map(valueFormat) },
    ],
    series: [
      { label: "Timestamp" },
      ...series.map((s): uPlot.Series => {
        const stroke = cssVar(s.color);
        const value = (_: uPlot, v: number | null) => (v == null ? "-" : valueFormat(v));
        if (s.kind === "points") {
          return {
            label: s.label,
            stroke,
            width: 0,
            value,
            paths: () => null,
            points: { show: triangle(s.marker ?? "up") },
          };
        }
        return {
          label: s.label,
          stroke,
          width: s.width ?? 1.5,
          value,
          points: { show: false },
          paths: s.kind === "step" ? uPlotLib.paths.stepped?.({ align: 1 }) : undefined,
        };
      }),
    ],
  };
}

async function exportPng(plot: uPlot, title: string, fileName: string) {
  const source = plot.ctx.canvas;
  const ratio = source.width / plot.width;
  const pad = 16 * ratio;
  const titleHeight = 28 * ratio;
  const canvas = document.createElement("canvas");
  canvas.width = source.width + pad * 2;
  canvas.height = source.height + pad * 2 + titleHeight;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.fillStyle = cssVar("--surface");
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = cssVar("--text");
  ctx.font = `600 ${14 * ratio}px ${cssVar("--font-geist-sans") || "sans-serif"}`;
  ctx.fillText(title, pad, pad + 14 * ratio);
  ctx.drawImage(source, pad, pad + titleHeight);
  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
  if (blob) downloadBlob(`${fileName}.png`, blob);
}

export function Chart(props: Props) {
  const { title, exportName, data } = props;
  const container = useRef<HTMLDivElement>(null);
  const plot = useRef<uPlot | null>(null);
  // The plot is rebuilt only when the data changes; the latest props are read from here when it is.
  const propsRef = useRef(props);
  useEffect(() => {
    propsRef.current = props;
  });

  useEffect(() => {
    const element = container.current;
    if (!element) return;
    let disposed = false;
    let observer: ResizeObserver | null = null;
    import("uplot").then(({ default: uPlotLib }) => {
      if (disposed) return;
      plot.current = new uPlotLib(buildOptions(uPlotLib, propsRef.current, element.clientWidth), data, element);
      observer = new ResizeObserver(() => {
        plot.current?.setSize({ width: element.clientWidth, height: propsRef.current.height ?? DEFAULT_HEIGHT });
      });
      observer.observe(element);
    });
    return () => {
      disposed = true;
      observer?.disconnect();
      plot.current?.destroy();
      plot.current = null;
    };
  }, [data]);

  return (
    <figure className={styles.chart}>
      <figcaption className={styles.chartHead}>
        <span>{title}</span>
        <button
          type="button"
          className={`${ui.button} ${ui.ghost} ${ui.buttonSmall}`}
          onClick={() => plot.current && exportPng(plot.current, title, exportName)}
        >
          Save PNG
        </button>
      </figcaption>
      <div ref={container} className={styles.chartBody} />
    </figure>
  );
}
