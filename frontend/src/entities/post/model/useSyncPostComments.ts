"use client";

import { useEffect } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { applyPostUpdate } from "@/entities/post/model/usePosts";
import { useRepositories } from "@/app/providers/RepositoryProvider";
import { useQueryAccountScope } from "@/app/providers/useQueryAccountScope";
import { showToast } from "@/shared/ui/toast";
import type { Post } from "@/shared/types";

export function useSyncPostComments(post: Post | null | undefined, enabled: boolean) {
  const { posts } = useRepositories();
  const queryClient = useQueryClient();
  const accountId = useQueryAccountScope();

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
    if (!enabled || !post?.id || !post.telegramMessageId) return;
    void mutation.mutate(post.id);
  }, [enabled, mutation, post?.id, post?.telegramMessageId]);
}
