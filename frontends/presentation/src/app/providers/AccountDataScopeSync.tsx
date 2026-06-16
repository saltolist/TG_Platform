"use client";

import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useComposerTargetStore } from "@/app/model/store/composer-target-store";
import { useProfileDraftStore } from "@/app/model/store/profile-draft-store";
import { useQueryAccountScope } from "@/app/providers/useQueryAccountScope";
import { queryKeys } from "@/shared/api/queryKeys";
import { setChannelMetricsAccount } from "@/shared/lib/channelMetricsDb";
import { resetFeedScrollSession } from "@/shared/lib/feed/feedScrollSession";

/** Keeps derived analytics DB and profile draft aligned with the active MSW account. */
export function AccountDataScopeSync() {
  const accountId = useQueryAccountScope();
  const queryClient = useQueryClient();
  const prevAccountIdRef = useRef<string | undefined>(undefined);

  useEffect(() => {
    setChannelMetricsAccount(accountId);
    if (prevAccountIdRef.current !== undefined && prevAccountIdRef.current !== accountId) {
      useProfileDraftStore.getState().resetForLogout();
      resetFeedScrollSession();
      void queryClient.removeQueries({ queryKey: queryKeys.profile.all(prevAccountIdRef.current) });
    }
    useComposerTargetStore.getState().hydrateForAccount(accountId);
    prevAccountIdRef.current = accountId;
  }, [accountId, queryClient]);

  return null;
}
