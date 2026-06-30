"use client";

import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useRepositories } from "@/app/providers/RepositoryProvider";
import { useAuthenticatedQueryEnabled } from "@/app/providers/useAuthenticatedQueryEnabled";
import { useQueryAccountScope } from "@/app/providers/useQueryAccountScope";
import { useProfileDraftStore } from "@/app/model/store/profile-draft-store";
import { queryKeys } from "@/shared/api/queryKeys";
import type { TelegramProfileConfig } from "@/shared/types";
import { normalizeTelegramProfileConfig } from "@/shared/lib/profile/normalizeProfileConfig";

const POLL_INTERVAL_MS = 5_000;

function mergeTelegramSyncFields(
  current: TelegramProfileConfig,
  telegram: TelegramProfileConfig,
): TelegramProfileConfig {
  return {
    ...current,
    importStatus: telegram.importStatus,
    importError: telegram.importError,
    importedPosts: telegram.importedPosts,
    lastSync: telegram.lastSync,
    syncStatus: telegram.syncStatus,
    syncError: telegram.syncError,
  };
}

/** Polls Telegram profile for live-sync updates and refreshes the posts feed when lastSync changes. */
export function TelegramLiveSyncPoll() {
  const { profile } = useRepositories();
  const queryClient = useQueryClient();
  const accountId = useQueryAccountScope();
  const enabled = useAuthenticatedQueryEnabled();
  const lastSyncRef = useRef<string | null>(null);

  useEffect(() => {
    if (!enabled) return;

    let cancelled = false;

    const tick = async () => {
      try {
        const telegram = normalizeTelegramProfileConfig(await profile.getTelegram());
        if (cancelled) return;

        const liveSyncActive =
          telegram.channelStatus === "connected" && telegram.syncMode !== "publish-only";
        if (!liveSyncActive) {
          lastSyncRef.current = null;
          return;
        }

        queryClient.setQueryData(queryKeys.profile.telegram(accountId), telegram);

        const current = useProfileDraftStore.getState().telegramProfileConfig;
        useProfileDraftStore.getState().updateTelegramConfig(mergeTelegramSyncFields(current, telegram));

        const previous = lastSyncRef.current;
        if (previous !== null && previous !== telegram.lastSync) {
          await queryClient.invalidateQueries({ queryKey: queryKeys.posts.all(accountId) });
        }
        lastSyncRef.current = telegram.lastSync;
      } catch {
        // Transient errors — keep polling.
      }
    };

    void tick();
    const intervalId = window.setInterval(() => {
      void tick();
    }, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [accountId, enabled, profile, queryClient]);

  return null;
}
