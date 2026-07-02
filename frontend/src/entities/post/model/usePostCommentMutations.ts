"use client";

import { useCallback } from "react";
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
