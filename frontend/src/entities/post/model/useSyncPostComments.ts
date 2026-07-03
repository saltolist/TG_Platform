"use client";

import { useEffect, useRef } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useTelegramProfile } from "@/entities/channel";
import { applyPostUpdate } from "@/entities/post/model/usePosts";
import { isPostCommentTelegramPending } from "@/entities/post/lib/isPostCommentTelegramPending";
import { useRepositories } from "@/app/providers/RepositoryProvider";
import { useQueryAccountScope } from "@/app/providers/useQueryAccountScope";
import { showToast } from "@/shared/ui/toast";
import type { Post } from "@/shared/types";

const BUSY_TELEGRAM_PATTERN = /занят|ограничил/i;
const MAX_SYNC_ATTEMPTS = 4;
const RETRY_DELAY_MS = 2_000;

function isTransientTelegramBusyError(post: Post): boolean {
  return Boolean(post.commentSyncError && BUSY_TELEGRAM_PATTERN.test(post.commentSyncError));
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function useSyncPostComments(post: Post | null | undefined, enabled: boolean) {
  const { posts } = useRepositories();
  const queryClient = useQueryClient();
  const accountId = useQueryAccountScope();
  const { data: telegramProfile } = useTelegramProfile();
  const commentsRevision = telegramProfile?.commentsRevision ?? 0;
  const lastRequestedKeyRef = useRef<string | null>(null);

  const mutation = useMutation({
    mutationFn: async (id: string) => {
      let latest: Post | undefined;
      for (let attempt = 0; attempt < MAX_SYNC_ATTEMPTS; attempt += 1) {
        if (attempt > 0) {
          await sleep(RETRY_DELAY_MS * attempt);
        }
        latest = await posts.syncComments(id);
        if (!latest || !isTransientTelegramBusyError(latest)) {
          return latest;
        }
      }
      return latest!;
    },
    onSuccess: (updatedPost) => {
      applyPostUpdate(queryClient, accountId, updatedPost);
      if (updatedPost.commentSyncError) {
        showToast({
          message: `Не удалось загрузить комментарии: ${updatedPost.commentSyncError}`,
          variant: "error",
        });
      }
    },
  });

  useEffect(() => {
    if (!enabled) {
      lastRequestedKeyRef.current = null;
      return;
    }
    if (!post?.id || !post.telegramMessageId) return;
    // Let useRetryPendingComments push unsent comments first — running a pull
    // concurrently competes for the single Telegram session.
    const hasPending = (post.comments ?? []).some((c) => isPostCommentTelegramPending(c, true));
    if (hasPending) return;
    const requestKey = `${post.id}:${post.telegramMessageId}:${commentsRevision}`;
    if (lastRequestedKeyRef.current === requestKey || mutation.isPending) return;
    lastRequestedKeyRef.current = requestKey;
    void mutation.mutate(post.id);
  }, [
    accountId,
    commentsRevision,
    enabled,
    mutation,
    post?.id,
    post?.telegramMessageId,
    post?.comments,
  ]);
}
