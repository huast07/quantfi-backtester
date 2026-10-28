import type { Metadata } from "next";
import { Suspense } from "react";

import { ResultsPage } from "@/features/results/results-page";

export const metadata: Metadata = { title: "Results" };

export default function Results() {
  // The run id is a query parameter, read on the client (the site is a static export).
  return (
    <Suspense>
      <ResultsPage />
    </Suspense>
  );
}
