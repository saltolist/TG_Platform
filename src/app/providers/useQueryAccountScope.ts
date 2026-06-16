"use client";

import { useAuth } from "@/app/providers/AuthProvider";
import { getQueryAccountIdFromAuth } from "@/shared/lib/auth/queryAccountScope";

/** MSW tenant id for React Query cache partitioning. */
export function useQueryAccountScope(): string {
  const { session } = useAuth();
  void session;
  return getQueryAccountIdFromAuth();
}
