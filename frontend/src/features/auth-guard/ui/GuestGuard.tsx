"use client";

import { useEffect, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/app/providers/AuthProvider";
import { routes } from "@/shared/lib/routes";

export function GuestGuard({ children }: { children: ReactNode }) {
  const { session, ready } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!ready || !session) return;
    router.replace(routes.home());
  }, [ready, router, session]);

  if (!ready) return null;
  if (session) return null;

  return children;
}
