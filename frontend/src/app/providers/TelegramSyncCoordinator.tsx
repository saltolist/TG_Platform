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
import { detectTelegramRevisionAdvance } from "@/shared/lib/profile/telegramRevisionPoll";

const POLL_INTERVAL_MS = 1_000;
const MAX_RECONNECT_DELAY_MS = 5_000;
const INITIAL_RECONNECT_DELAY_MS = 1_000;

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

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

/**
 * Subscribes to backend telegram sync revisions (SSE) and drives client cache updates:
 * - ``syncRevision`` / ``metricsRevision`` → refetch post list
 * - ``commentsRevision`` / ``metricsRevision`` → refetch the currently open post
 *
 * Falls back to 1s polling when the SSE stream is unavailable.
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
    let pollIntervalId: number | null = null;
    let reconnectDelayMs = INITIAL_RECONNECT_DELAY_MS;
    const abortController = new AbortController();

    const stopPolling = () => {
      if (pollIntervalId === null) return;
      window.clearInterval(pollIntervalId);
      pollIntervalId = null;
    };

    const applyTelegramSync = async (telegram: TelegramProfileConfig) => {
      const liveSyncActive =
        telegram.channelStatus === "connected" && telegram.syncMode !== "publish-only";
      if (!liveSyncActive) {
        syncRevisionRef.current = null;
        commentsRevisionRef.current = null;
        metricsRevisionRef.current = null;
        lastSyncRef.current = null;
        return;
      }

      const syncRevision = telegram.syncRevision ?? 0;
      const commentsRevision = telegram.commentsRevision ?? 0;
      const metricsRevision = telegram.metricsRevision ?? 0;
      const lastSync = telegram.lastSync ?? "—";
      const previousLastSync = lastSyncRef.current;

      const baselines = {
        syncRevision:
          syncRevisionRef.current ??
          cachedTelegramRevision(queryClient, accountId, "syncRevision") ??
          0,
        commentsRevision:
          commentsRevisionRef.current ??
          cachedTelegramRevision(queryClient, accountId, "commentsRevision") ??
          0,
        metricsRevision:
          metricsRevisionRef.current ??
          cachedTelegramRevision(queryClient, accountId, "metricsRevision") ??
          0,
      };

      const {
        syncRevisionAdvanced,
        commentsRevisionAdvanced,
        metricsRevisionAdvanced,
        lastSyncAdvanced,
      } = detectTelegramRevisionAdvance(telegram, baselines, previousLastSync);

      queryClient.setQueryData(queryKeys.profile.telegram(accountId), telegram);

      const current = useProfileDraftStore.getState().telegramProfileConfig;
      useProfileDraftStore.getState().updateTelegramConfig(mergeTelegramSyncFields(current, telegram));

      if (syncRevisionAdvanced || lastSyncAdvanced || metricsRevisionAdvanced) {
        await queryClient.refetchQueries({ queryKey: queryKeys.posts.list(accountId) });
      }
      syncRevisionRef.current = syncRevision;
      lastSyncRef.current = lastSync;

      const shouldRefreshOpenPost = commentsRevisionAdvanced || metricsRevisionAdvanced;

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

    const applyTelegramMeta = async (meta: Record<string, unknown>) => {
      const cached =
        queryClient.getQueryData<TelegramProfileConfig>(queryKeys.profile.telegram(accountId)) ??
        normalizeTelegramProfileConfig({});
      const telegram = normalizeTelegramProfileConfig({
        ...cached,
        ...meta,
      });
      await applyTelegramSync(telegram);
    };

    const pollTelegramProfile = async () => {
      try {
        const telegram = normalizeTelegramProfileConfig(await profile.getTelegram());
        if (cancelled) return;
        await applyTelegramSync(telegram);
      } catch {
        // Transient errors — keep polling.
      }
    };

    const startPolling = () => {
      if (pollIntervalId !== null) return;
      void pollTelegramProfile();
      pollIntervalId = window.setInterval(() => {
        void pollTelegramProfile();
      }, POLL_INTERVAL_MS);
    };

    const connectStream = async () => {
      while (!cancelled) {
        try {
          await profile.streamTelegramSync(
            (meta) => {
              if (cancelled) return;
              stopPolling();
              reconnectDelayMs = INITIAL_RECONNECT_DELAY_MS;
              void applyTelegramMeta(meta);
            },
            abortController.signal,
          );
        } catch {
          if (cancelled || abortController.signal.aborted) return;
        }
        if (cancelled || abortController.signal.aborted) return;
        startPolling();
        await sleep(reconnectDelayMs);
        reconnectDelayMs = Math.min(reconnectDelayMs * 2, MAX_RECONNECT_DELAY_MS);
      }
    };

    const onFocus = () => {
      void pollTelegramProfile();
    };

    void connectStream();
    window.addEventListener("focus", onFocus);

    return () => {
      cancelled = true;
      abortController.abort();
      stopPolling();
      window.removeEventListener("focus", onFocus);
    };
  }, [accountId, enabled, posts, profile, queryClient]);

  return null;
}
