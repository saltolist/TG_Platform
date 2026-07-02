"use client";

import { useEffect, useRef } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { applyPostUpdate } from "@/entities/post/model/usePosts";
import { isPostCommentTelegramPending } from "@/entities/post/lib/isPostCommentTelegramPending";
import { useRepositories } from "@/app/providers/RepositoryProvider";
import { useQueryAccountScope } from "@/app/providers/useQueryAccountScope";
import { showToast } from "@/shared/ui/toast";
import type { Post } from "@/shared/types";

export function useSyncPostComments(post: Post | null | undefined, enabled: boolean) {
  const { posts } = useRepositories();
  const queryClient = useQueryClient();
  const accountId = useQueryAccountScope();
  const lastRequestedKeyRef = useRef<string | null>(null);

  const mutation = useMutation({
    mutationFn: (id: string) => posts.syncComments(id),
    onSuccess: (updatedPost) => {
      applyPostUpdate(queryClient, accountId, updatedPost);
      if (updatedPost.commentSyncError) {
        showToast({
          message: `Не удалось синхронизировать комментарии: ${updatedPost.commentSyncError}`,
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
    const requestKey = `${post.id}:${post.telegramMessageId}`;
    if (lastRequestedKeyRef.current === requestKey || mutation.isPending) return;
    lastRequestedKeyRef.current = requestKey;
    void mutation.mutate(post.id);
  }, [enabled, mutation, post?.id, post?.telegramMessageId, post?.comments]);
}
