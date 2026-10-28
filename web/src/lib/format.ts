const signedWhole = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0, signDisplay: "exceptZero" });
const whole = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const decimal = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });
const dateTimeFormat = new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" });

/** PnL as the CLI prints it: "+1,234", "-56", "0". */
export const formatPnl = (value: number): string => signedWhole.format(value);
export const formatWhole = (value: number): string => whole.format(value);
export const formatPrice = (value: number): string => decimal.format(value);
export const formatPercent = (fraction: number): string => `${Math.round(fraction * 100)}%`;
export const formatDateTime = (iso: string): string => dateTimeFormat.format(new Date(iso));

export function formatDuration(ms: number): string {
  const seconds = Math.max(0, Math.round(ms / 1000));
  if (seconds < 60) return `${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  if (minutes < 10 && rest > 0) return `${minutes} min ${rest} s`;
  return `${Math.round(seconds / 60)} min`;
}
