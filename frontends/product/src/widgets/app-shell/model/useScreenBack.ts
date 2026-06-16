"use client";

import { usePathname, useRouter } from "next/navigation";
import { useCallback } from "react";

import { resolveScreenBackAction } from "@/shared/lib/hooks/useScreenBack";
import { confirmScreenLeave } from "@/widgets/app-shell/lib/guardedNavigation";

export function useScreenBack() {
  const router = useRouter();
  const pathname = usePathname();

  return useCallback(async () => {
    if (!(await confirmScreenLeave())) return;
    const params =
      typeof window !== "undefined"
        ? new URLSearchParams(window.location.search)
        : new URLSearchParams();
    const action = resolveScreenBackAction(pathname ?? "/", params);
    if (action.type === "back") router.back();
    else router.push(action.href);
  }, [router, pathname]);
}
