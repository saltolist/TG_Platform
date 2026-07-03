"use client";

import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { enqueueSerialPostPatch } from "@/entities/post/lib/enqueueSerialPostPatch";
import { applyPostUpdate, useUpdatePost } from "@/entities/post/model/usePosts";
import { isPostCommentTelegramPending } from "@/entities/post/lib/isPostCommentTelegramPending";
import { useRepositories } from "@/app/providers/RepositoryProvider";
import { useQueryAccountScope } from "@/app/providers/useQueryAccountScope";
import type { Post } from "@/shared/types";

/**
 * Re-push platform comments that never reached Telegram (e.g. a previous send
 * failed on a network/VPN drop). Runs once per post when the comments tab opens
 * and there are comments without a ``telegramMessageId``.
 */
export function useRetryPendingComments(post: Post | null | undefined, enabled: boolean) {
  const { posts } = useRepositories();
  const updatePost = useUpdatePost();
  const queryClient = useQueryClient();
  const accountId = useQueryAccountScope();
  const retriedKeyRef = useRef<string | null>(null);

  useEffect(() => {
    if (!enabled) {
      retriedKeyRef.current = null;
      return;
    }
    if (!post?.id || !post.telegramMessageId) return;

    const pending = (post.comments ?? []).filter((c) => isPostCommentTelegramPending(c, true));
    if (pending.length === 0) return;

    const retryKey = `${post.id}:${pending.map((c) => c.id).join(",")}`;
    if (retriedKeyRef.current === retryKey || updatePost.isPending) return;
    retriedKeyRef.current = retryKey;

    void enqueueSerialPostPatch(post.id, async () => {
      let latest = post;
      try {
        latest = await posts.get(post.id);
        applyPostUpdate(queryClient, accountId, latest);
      } catch {
        return;
      }

      const comments = latest.comments ?? [];
      const stillPending = comments.filter((c) => isPostCommentTelegramPending(c, true));
      if (stillPending.length === 0) return;

      await updatePost.mutateAsync({ id: post.id, patch: { comments } }).catch(() => {
        // Errors surface via commentSyncError in useUpdatePost's onSuccess toast.
      });
    });
  }, [
    accountId,
    enabled,
    post,
    post?.id,
    post?.telegramMessageId,
    post?.comments,
    posts,
    queryClient,
    updatePost,
  ]);
}
