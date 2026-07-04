"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useTelegramProfile } from "@/entities/channel";
import { useRepositories } from "@/app/providers/RepositoryProvider";
import { useQueryAccountScope } from "@/app/providers/useQueryAccountScope";
import type { CommentDeleteTombstone } from "@/entities/post/lib/mergePostComments";
import { enqueueSerialPostPatch } from "@/entities/post/lib/enqueueSerialPostPatch";
import { getCachedPost, setCachedPost } from "@/entities/post/lib/getCachedPost";
import { applyPostUpdate, useUpdatePost } from "@/entities/post/model/usePosts";
import type { PostComment } from "@/shared/types";

export function useAddPostComment() {
  const updatePost = useUpdatePost();
  const { posts } = useRepositories();
  const queryClient = useQueryClient();
  const accountId = useQueryAccountScope();

  const addComment = useCallback(
    async (postId: string, comment: PostComment) => {
      const post = getCachedPost(queryClient, postId);
      if (!post) return;
      const previousComments = post.comments ?? [];
      const comments = [...previousComments, comment];

      // Show the new comment immediately — do not wait for the serial PATCH queue or Telegram.
      setCachedPost(queryClient, { ...post, comments });

      await enqueueSerialPostPatch(postId, async () => {
        const latest = getCachedPost(queryClient, postId);
        if (!latest) return;
        const latestComments = latest.comments ?? [];
        const patchComments = latestComments.some((item) => item.id === comment.id)
          ? latestComments
          : [...latestComments, comment];
        try {
          await updatePost.mutateAsync({ id: postId, patch: { comments: patchComments } });
        } catch (error) {
          try {
            const serverPost = await posts.get(postId);
            const savedOnServer = (serverPost.comments ?? []).some((item) => item.id === comment.id);
            if (savedOnServer) {
              applyPostUpdate(queryClient, accountId, serverPost);
              return;
            }
          } catch {
            // Refetch failed — fall through to rollback.
          }
          setCachedPost(queryClient, { ...post, comments: previousComments });
          throw error;
        }
      });
    },
    [accountId, posts, queryClient, updatePost],
  );

  return { addComment, isPending: updatePost.isPending };
}

export function useDeletePostComment() {
  const updatePost = useUpdatePost();
  const queryClient = useQueryClient();
  const { data: telegramProfile } = useTelegramProfile();
  const commentsRevision = telegramProfile?.commentsRevision ?? 0;
  const prevCommentsRevisionRef = useRef(commentsRevision);
  const [syncingDeleteById, setSyncingDeleteById] = useState<
    Map<string, CommentDeleteTombstone>
  >(() => new Map());

  useEffect(() => {
    const previousRevision = prevCommentsRevisionRef.current;
    if (commentsRevision > previousRevision) {
      const delta = commentsRevision - previousRevision;
      setSyncingDeleteById((current) => {
        if (current.size === 0) return current;
        const next = new Map(current);
        for (const commentId of [...next.keys()].slice(0, delta)) {
          next.delete(commentId);
        }
        return next.size === current.size ? current : next;
      });
    }
    prevCommentsRevisionRef.current = commentsRevision;
  }, [commentsRevision]);

  const deleteComment = useCallback(
    async (postId: string, commentId: string) => {
      const post = getCachedPost(queryClient, postId);
      if (!post) return;
      const previousComments = post.comments ?? [];
      const target = previousComments.find((item) => item.id === commentId);
      if (!target) return;

      const needsTelegramSync = Boolean(post.telegramMessageId && target.telegramMessageId);
      if (needsTelegramSync) {
        const deleteIndex = previousComments.findIndex((item) => item.id === commentId);
        setSyncingDeleteById((prev) =>
          new Map(prev).set(commentId, {
            comment: target,
            index: deleteIndex >= 0 ? deleteIndex : previousComments.length - 1,
          }),
        );
      }

      await enqueueSerialPostPatch(postId, async () => {
        const latest = getCachedPost(queryClient, postId);
        if (!latest) return;
        const latestComments = latest.comments ?? [];
        const comments = latestComments.filter((item) => item.id !== commentId);
        if (comments.length === latestComments.length) return;

        try {
          await updatePost.mutateAsync({ id: postId, patch: { comments } });
        } catch (error) {
          setSyncingDeleteById((prev) => {
            const next = new Map(prev);
            next.delete(commentId);
            return next;
          });
          throw error;
        }
      });
    },
    [queryClient, updatePost],
  );

  const deletingCommentIds = useMemo(
    () => new Set(syncingDeleteById.keys()),
    [syncingDeleteById],
  );

  return { deleteComment, deletingCommentIds, syncingDeleteById };
}
