/** Saves a Blob as a file through a temporary link (no server involved). */
export function downloadBlob(filename: string, blob: Blob): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  // Give the browser a moment to start the download before the URL goes away.
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

export function downloadText(filename: string, text: string, type = "text/plain"): void {
  downloadBlob(filename, new Blob([text], { type: `${type};charset=utf-8` }));
}

export function caseCsvNames(caseId: string, seed: number, day: number): { prices: string; trades: string } {
  const prefix = `${caseId}_seed${seed}`;
  return { prices: `${prefix}_prices_round_1_day_${day}.csv`, trades: `${prefix}_trades_round_1_day_${day}.csv` };
}
