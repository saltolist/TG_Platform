"use client";

import { useAuth } from "@/app/providers/AuthProvider";

/** Gate React Query until auth is ready; presentation guests use the presentation account. */
export function useAuthenticatedQueryEnabled(): boolean {
  const { session, ready, isPresentationMode } = useAuth();
  return ready && (!!session || isPresentationMode);
}
