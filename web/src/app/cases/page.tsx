import type { Metadata } from "next";

import { CasesPage } from "@/features/cases/cases-page";

export const metadata: Metadata = { title: "Cases" };

export default function Cases() {
  return <CasesPage />;
}
