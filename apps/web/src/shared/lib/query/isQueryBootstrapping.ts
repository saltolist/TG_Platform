/** Show a full-screen loading placeholder only when the query has no cached payload yet. */
export function isQueryBootstrapping<T>(
  isLoading: boolean,
  data: T | undefined,
): boolean {
  return isLoading && data == null;
}

/** List queries: keep showing content while a background refetch runs. */
export function isListQueryBootstrapping(
  isLoading: boolean,
  items: readonly unknown[] | undefined,
): boolean {
  return isLoading && (items == null || items.length === 0);
}
