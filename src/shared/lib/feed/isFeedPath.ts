export function isFeedPath(pathname: string): boolean {
  const normalized = pathname.endsWith("/") && pathname.length > 1 ? pathname.slice(0, -1) : pathname;
  return normalized === "/feed";
}
