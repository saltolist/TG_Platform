"use client";

import { useEffect, useRef } from "react";

import { useUpdatePost } from "@/entities/post/model/usePosts";
import { isPostCommentTelegramPending } from "@/entities/post/lib/isPostCommentTelegramPending";
import type { Post } from "@/shared/types";

/**
 * Re-push platform comments that never reached Telegram (e.g. a previous send
 * failed on a network/VPN drop). Runs once per post when the comments tab opens
 * and there are comments without a ``telegramMessageId``.
 */
export function useRetryPendingComments(post: Post | null | undefined, enabled: boolean) {
  const updatePost = useUpdatePost();
  const retriedKeyRef = useRef<string | null>(null);

  useEffect(() => {
    if (!enabled) {
      retriedKeyRef.current = null;
      return;
    }
    if (!post?.id || !post.telegramMessageId) return;

    const comments = post.comments ?? [];
    const pending = comments.filter((c) => isPostCommentTelegramPending(c, true));
    if (pending.length === 0) return;

    const retryKey = `${post.id}:${pending.map((c) => c.id).join(",")}`;
    if (retriedKeyRef.current === retryKey || updatePost.isPending) return;
    retriedKeyRef.current = retryKey;

    void updatePost.mutateAsync({ id: post.id, patch: { comments } }).catch(() => {
      // Errors surface via commentSyncError in useUpdatePost's onSuccess toast.
    });
  }, [enabled, post?.id, post?.telegramMessageId, post?.comments, updatePost]);
}
