"use client";

import { usePathname } from "next/navigation";
import { useCallback } from "react";

import { useProfileDraftStore } from "@/app/model/store/profile-draft-store";
import { useUiStore } from "@/app/model/store/ui-store";
import { parseAppPath } from "@/shared/lib/routes";

export function useNavigation() {
  const pathname = usePathname();
  const parsed = parseAppPath(pathname ?? "/");
  const screen = parsed?.screen ?? "home";
  const discardProfileEdits = useCallback(() => {
    useProfileDraftStore.getState().discardEdits();
    useUiStore.getState().clearProfileDirtyFlags();
  }, []);

  return {
    screen,
    discardProfileEdits,
  };
}
