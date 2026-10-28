// Readable text for a case's modifier parameters, as listed on the case library page.
import type { CaseInfo } from "@/py/types";

type Modifier = CaseInfo["modifiers"][number];

const number = new Intl.NumberFormat("en-US", { maximumFractionDigits: 3 });

function formatValue(value: unknown): string {
  if (typeof value === "number") return number.format(value);
  if (Array.isArray(value)) {
    const isRange = value.length === 2 && value.every((v) => typeof v === "number");
    return isRange ? `${formatValue(value[0])} to ${formatValue(value[1])}` : value.map(formatValue).join(", ");
  }
  if (value !== null && typeof value === "object") {
    return Object.entries(value)
      .map(([key, inner]) => `${key} ${formatValue(inner)}`)
      .join(", ");
  }
  return String(value);
}

/** The parameters that are set, as [name, value] pairs; nulls and false flags are left out. */
export function modifierParams(modifier: Modifier): Array<[string, string]> {
  return Object.entries(modifier)
    .filter(([key, value]) => key !== "kind" && value !== null && value !== false)
    .map(([key, value]) => [key.replaceAll("_", " "), formatValue(value)]);
}

/** "10% to 40% of the day". */
export function eventWindowText([start, end]: [number, number]): string {
  return `${Math.round(start * 100)}% to ${Math.round(end * 100)}% of the day`;
}
