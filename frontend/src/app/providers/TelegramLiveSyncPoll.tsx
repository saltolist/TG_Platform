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
    syncRevision: telegram.syncRevision,
  };
}

/** Polls backend telegram profile; refetches posts when syncRevision advances. */
export function TelegramLiveSyncPoll() {
  const { profile } = useRepositories();
  const queryClient = useQueryClient();
  const accountId = useQueryAccountScope();
  const enabled = useAuthenticatedQueryEnabled();
  const syncRevisionRef = useRef<number | null>(null);
  const lastSyncRef = useRef<string | null>(null);

  useEffect(() => {
    if (!enabled) return;

    let cancelled = false;

    const applyTelegramPoll = async (telegram: TelegramProfileConfig) => {
      const liveSyncActive =
        telegram.channelStatus === "connected" && telegram.syncMode !== "publish-only";
      if (!liveSyncActive) {
        syncRevisionRef.current = null;
        lastSyncRef.current = null;
        return;
      }

      queryClient.setQueryData(queryKeys.profile.telegram(accountId), telegram);

      const current = useProfileDraftStore.getState().telegramProfileConfig;
      useProfileDraftStore.getState().updateTelegramConfig(mergeTelegramSyncFields(current, telegram));

      const previousRevision = syncRevisionRef.current;
      const previousLastSync = lastSyncRef.current;
      const revision = telegram.syncRevision ?? 0;
      const lastSync = telegram.lastSync ?? "";

      const shouldRefreshPosts =
        previousRevision !== null &&
        (revision > previousRevision || (lastSync && lastSync !== previousLastSync));

      if (shouldRefreshPosts) {
        await queryClient.refetchQueries({ queryKey: queryKeys.posts.list(accountId) });
      }

      syncRevisionRef.current = revision;
      lastSyncRef.current = lastSync;
    };

    const tick = async () => {
      try {
        const telegram = normalizeTelegramProfileConfig(await profile.getTelegram());
        if (cancelled) return;
        await applyTelegramPoll(telegram);
      } catch {
        // Transient errors — keep polling.
      }
    };

    const onFocus = () => {
      void tick();
    };

    void tick();
    const intervalId = window.setInterval(() => {
      void tick();
    }, POLL_INTERVAL_MS);
    window.addEventListener("focus", onFocus);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
      window.removeEventListener("focus", onFocus);
    };
  }, [accountId, enabled, profile, queryClient]);

  return null;
}
