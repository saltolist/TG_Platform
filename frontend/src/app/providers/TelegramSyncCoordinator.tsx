"use client";

import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useRepositories } from "@/app/providers/RepositoryProvider";
import { useAuthenticatedQueryEnabled } from "@/app/providers/useAuthenticatedQueryEnabled";
import { useQueryAccountScope } from "@/app/providers/useQueryAccountScope";
import { useNavigationStore } from "@/app/model/store/navigation-store";
import { useProfileDraftStore } from "@/app/model/store/profile-draft-store";
import { applyPostUpdate } from "@/entities/post/model/usePosts";
import { queryKeys } from "@/shared/api/queryKeys";
import type { TelegramProfileConfig } from "@/shared/types";
import { mergeTelegramSyncFields } from "@/shared/lib/profile/mergeTelegramSyncFields";
import { normalizeTelegramProfileConfig } from "@/shared/lib/profile/normalizeProfileConfig";

const POLL_INTERVAL_MS = 1_000;

function cachedTelegramRevision(
  queryClient: ReturnType<typeof useQueryClient>,
  accountId: string,
  field: "syncRevision" | "commentsRevision" | "metricsRevision",
): number | null {
  const cached = queryClient.getQueryData<TelegramProfileConfig>(
    queryKeys.profile.telegram(accountId),
  );
  if (!cached) return null;
  const value = cached[field];
  return typeof value === "number" ? value : 0;
}

/**
 * Polls backend telegram profile and drives client cache updates:
 * - ``syncRevision`` / ``metricsRevision`` → refetch post list
 * - ``commentsRevision`` / ``metricsRevision`` → refetch the currently open post
 *
 * ``usePollOpenPost`` remains as a fallback while a post page is open.
 */
export function TelegramSyncCoordinator() {
  const { profile, posts } = useRepositories();
  const queryClient = useQueryClient();
  const accountId = useQueryAccountScope();
  const enabled = useAuthenticatedQueryEnabled();
  const syncRevisionRef = useRef<number | null>(null);
  const commentsRevisionRef = useRef<number | null>(null);
  const metricsRevisionRef = useRef<number | null>(null);
  const lastSyncRef = useRef<string | null>(null);

  useEffect(() => {
    if (!enabled) return;

    let cancelled = false;

    const applyTelegramPoll = async (telegram: TelegramProfileConfig) => {
      const liveSyncActive =
        telegram.channelStatus === "connected" && telegram.syncMode !== "publish-only";
      if (!liveSyncActive) {
        syncRevisionRef.current = null;
        commentsRevisionRef.current = null;
        metricsRevisionRef.current = null;
        lastSyncRef.current = null;
        return;
      }

      queryClient.setQueryData(queryKeys.profile.telegram(accountId), telegram);

      const current = useProfileDraftStore.getState().telegramProfileConfig;
      useProfileDraftStore.getState().updateTelegramConfig(mergeTelegramSyncFields(current, telegram));

      const syncRevision = telegram.syncRevision ?? 0;
      const previousSyncRevision = syncRevisionRef.current;
      const baselineSyncRevision =
        previousSyncRevision ?? cachedTelegramRevision(queryClient, accountId, "syncRevision");
      const lastSync = telegram.lastSync ?? "—";
      const previousLastSync = lastSyncRef.current;

      const syncRevisionAdvanced =
        baselineSyncRevision !== null && syncRevision > baselineSyncRevision;
      const lastSyncAdvanced =
        previousLastSync !== null &&
        lastSync !== "—" &&
        previousLastSync !== "—" &&
        lastSync !== previousLastSync;

      const commentsRevision = telegram.commentsRevision ?? 0;
      const metricsRevision = telegram.metricsRevision ?? 0;
      const previousCommentsRevision = commentsRevisionRef.current;
      const previousMetricsRevision = metricsRevisionRef.current;
      const baselineCommentsRevision =
        previousCommentsRevision ??
        cachedTelegramRevision(queryClient, accountId, "commentsRevision");
      const baselineMetricsRevision =
        previousMetricsRevision ?? cachedTelegramRevision(queryClient, accountId, "metricsRevision");

      const metricsRevisionAdvanced =
        baselineMetricsRevision !== null && metricsRevision > baselineMetricsRevision;

      if (syncRevisionAdvanced || lastSyncAdvanced || metricsRevisionAdvanced) {
        await queryClient.refetchQueries({ queryKey: queryKeys.posts.list(accountId) });
      }
      syncRevisionRef.current = syncRevision;
      lastSyncRef.current = lastSync;

      const shouldRefreshOpenPost =
        (baselineCommentsRevision !== null && commentsRevision > baselineCommentsRevision) ||
        (baselineMetricsRevision !== null && metricsRevision > baselineMetricsRevision);

      if (shouldRefreshOpenPost) {
        const postId = useNavigationStore.getState().currentPostId;
        if (postId) {
          try {
            const fresh = await posts.get(postId);
            if (!cancelled) {
              applyPostUpdate(queryClient, accountId, fresh);
            }
          } catch {
            // Transient errors — usePollOpenPost will retry.
          }
        }
      }
      commentsRevisionRef.current = commentsRevision;
      metricsRevisionRef.current = metricsRevision;
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
  }, [accountId, enabled, posts, profile, queryClient]);

  return null;
}
