/** GitHub Pages / static host prefix (no trailing slash). Empty = site root. */
export const BASE_PATH = (process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/$/, "");

export const API_V1 = `${BASE_PATH}/api/v1`;

/** `/api/v1/.../` — trailing slash matches Next.js `trailingSlash: true` and avoids 308→404. */
export function apiV1Path(subpath: string): string {
  const normalized = subpath.replace(/^\/+|\/+$/g, "");
  if (!normalized) return `${API_V1}/`;
  return `${API_V1}/${normalized}/`;
}

/** MSW v2 handler pattern — bare `/api/...` paths are not matched; `*` prefix is required. */
export function apiV1MswPath(subpath: string): string {
  return `*${apiV1Path(subpath)}`;
}
