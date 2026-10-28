"use client";

import { useEffect, useState } from "react";

import { pythonClient } from "@/py/client";
import type { PoolStatus } from "@/worker/pool";

/** The shared worker pool's live status; null until the page has mounted. */
export function usePoolStatus(): PoolStatus | null {
  const [status, setStatus] = useState<PoolStatus | null>(null);
  useEffect(() => pythonClient().pool.subscribe(setStatus), []);
  return status;
}
