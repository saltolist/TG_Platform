"use client";

import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { getCachedPost, setCachedPost } from "@/entities/post/lib/getCachedPost";
import type { PostComment } from "@/shared/types";

import { useUpdatePost } from "./usePosts";

export function useAddPostComment() {
  const updatePost = useUpdatePost();
  const queryClient = useQueryClient();

  return useCallback(
    async (postId: string, comment: PostComment) => {
      const post = getCachedPost(queryClient, postId);
      if (!post) return;
      const comments = [...(post.comments ?? []), comment];
      const updated = { ...post, comments };
      await updatePost.mutateAsync({ id: postId, patch: { comments } });

      setCachedPost(queryClient, updated);
    },
    [queryClient, updatePost],
  );
}
