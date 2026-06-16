/**
 * Data source modes (see stack.md / local-first.md):
 * - seed: direct in-memory repositories (unit tests, NEXT_PUBLIC_USE_MSW=0 in dev)
 * - msw: HTTP repositories + MSW intercepts `/api/v1/*` (default in development)
 * - http: real REST API when NEXT_PUBLIC_API_BASE_URL is set and MSW is off
 */

export const USE_MSW =
  process.env.NEXT_PUBLIC_USE_MSW === "1" ||
  (process.env.NEXT_PUBLIC_USE_MSW !== "0" && process.env.NODE_ENV === "development");

export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL ??
  process.env.NEXT_PUBLIC_SYNC_API_URL ??
  ""
).replace(/\/$/, "");

export const API_MODE = !USE_MSW && API_BASE_URL.length > 0;

export type DataSourceMode = "http" | "msw" | "seed";

export function getDataSourceMode(): DataSourceMode {
  if (API_MODE) return "http";
  if (USE_MSW) return "msw";
  return "seed";
}
