import type { Metadata } from "next";

import { HistoryPage } from "@/features/history/history-page";

export const metadata: Metadata = { title: "History" };

export default function History() {
  return <HistoryPage />;
}
