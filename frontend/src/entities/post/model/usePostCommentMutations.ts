"use client";

import { useCallback, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { getCachedPost, setCachedPost } from "@/entities/post/lib/getCachedPost";
import type { PostComment } from "@/shared/types";

import { useUpdatePost } from "./usePosts";

export function useAddPostComment() {
  const updatePost = useUpdatePost();
  const queryClient = useQueryClient();

  const addComment = useCallback(
    async (postId: string, comment: PostComment) => {
      const post = getCachedPost(queryClient, postId);
      if (!post) return;
      const previousComments = post.comments ?? [];
      const comments = [...previousComments, comment];
      setCachedPost(queryClient, { ...post, comments });
      try {
        await updatePost.mutateAsync({ id: postId, patch: { comments } });
      } catch (error) {
        setCachedPost(queryClient, { ...post, comments: previousComments });
        throw error;
      }
    },
    [queryClient, updatePost],
  );

  return { addComment, isPending: updatePost.isPending };
}

export function useDeletePostComment() {
  const updatePost = useUpdatePost();
  const queryClient = useQueryClient();
  const [deletingCommentIds, setDeletingCommentIds] = useState<ReadonlySet<string>>(
    () => new Set(),
  );

  const deleteComment = useCallback(
    async (postId: string, commentId: string) => {
      const post = getCachedPost(queryClient, postId);
      if (!post) return;
      const previousComments = post.comments ?? [];
      const comments = previousComments.filter((item) => item.id !== commentId);
      if (comments.length === previousComments.length) return;

      setDeletingCommentIds((prev) => new Set(prev).add(commentId));
      try {
        await updatePost.mutateAsync({ id: postId, patch: { comments } });
      } catch (error) {
        throw error;
      } finally {
        setDeletingCommentIds((prev) => {
          const next = new Set(prev);
          next.delete(commentId);
          return next;
        });
      }
    },
    [queryClient, updatePost],
  );

  return { deleteComment, deletingCommentIds };
}
