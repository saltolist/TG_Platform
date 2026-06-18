/** Shared React Query options for profile endpoints (backend may warm up after Docker start). */
export const profileQueryOptions = {
  staleTime: 5 * 60_000,
  retry: 5,
  retryDelay: (attempt: number) => Math.min(1000 * 2 ** attempt, 8_000),
} as const;
