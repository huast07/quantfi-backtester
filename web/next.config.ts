import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Static files only: strategies run in the visitor's browser (Pyodide workers), so there is no server code.
  // Server-only features (Cache Components, Partial Prefetching) are left off: a static export cannot serve them.
  output: "export",
};

export default nextConfig;
