// Downloads one simulated day of a case as the two CSVs the competition ships (prices and trades).
import { pythonClient } from "@/py/client";

import { caseCsvNames, downloadText } from "./download";

export async function downloadCaseDay(caseId: string, seed: number): Promise<void> {
  const day = await pythonClient().call("case_csv", { case_id: caseId, seed });
  const names = caseCsvNames(caseId, seed, day.day);
  downloadText(names.prices, day.prices, "text/csv");
  downloadText(names.trades, day.trades, "text/csv");
}
