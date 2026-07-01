"use client";

import { useMutation, useMutationState, useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/shared/api/queryKeys";
import { useRepositories } from "@/app/providers/RepositoryProvider";
import { useAuthenticatedQueryEnabled } from "@/app/providers/useAuthenticatedQueryEnabled";
import { useQueryAccountScope } from "@/app/providers/useQueryAccountScope";
import { showToast } from "@/shared/ui/toast";
import type { Post } from "@/shared/types";

function applyPostUpdate(
  queryClient: ReturnType<typeof useQueryClient>,
  accountId: string,
  updatedPost: Post,
) {
  const normalized: Post =
    updatedPost.status === "published"
      ? { ...updatedPost, created: undefined }
      : updatedPost;
  queryClient.setQueryData(queryKeys.posts.detail(accountId, normalized.id), normalized);
  queryClient.setQueryData<Post[]>(queryKeys.posts.list(accountId), (prev) =>
    prev?.map((p) => (p.id === normalized.id ? normalized : p)),
  );
}

export function usePosts() {
  const { posts } = useRepositories();
  const enabled = useAuthenticatedQueryEnabled();
  const accountId = useQueryAccountScope();

  return useQuery({
    queryKey: queryKeys.posts.list(accountId),
    queryFn: () => posts.list(),
    enabled,
    placeholderData: (previous) => previous,
    refetchInterval: (query) => {
      const items = query.state.data;
      return items?.some((post) => post.telegramSyncPending) ? 3000 : false;
    },
  });
}

export function usePost(id: string) {
  const { posts } = useRepositories();
  const queryClient = useQueryClient();
  const enabled = useAuthenticatedQueryEnabled();
  const accountId = useQueryAccountScope();

  return useQuery({
    queryKey: queryKeys.posts.detail(accountId, id),
    queryFn: async () => {
      const list = await posts.list();
      const post = list.find((p) => p.id === id);
      if (!post) throw new Error(`Post ${id} not found`);
      return post;
    },
    placeholderData: () => {
      const list = queryClient.getQueryData<Post[]>(queryKeys.posts.list(accountId));
      return list?.find((p) => p.id === id);
    },
    enabled: enabled && !!id,
  });
}

export function useCreatePost() {
  const { posts } = useRepositories();
  const queryClient = useQueryClient();
  const accountId = useQueryAccountScope();

  return useMutation({
    mutationFn: (post: Post) => posts.create(post),
    onMutate: async (post) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.posts.all(accountId) });
      const previous = queryClient.getQueryData<Post[]>(queryKeys.posts.list(accountId));
      queryClient.setQueryData<Post[]>(queryKeys.posts.list(accountId), (prev = []) => [
        post,
        ...prev.filter((p) => p.id !== post.id),
      ]);
      queryClient.setQueryData(queryKeys.posts.detail(accountId, post.id), post);
      return { previous };
    },
    onError: (_error, _post, context) => {
      if (context?.previous) {
        queryClient.setQueryData(queryKeys.posts.list(accountId), context.previous);
      }
    },
  });
}

export function useUpdatePost() {
  const { posts } = useRepositories();
  const queryClient = useQueryClient();
  const accountId = useQueryAccountScope();

  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Partial<Post> }) => posts.update(id, patch),
    onSuccess: (updatedPost) => {
      applyPostUpdate(queryClient, accountId, updatedPost);
      if (updatedPost.telegramSyncError) {
        showToast({
          message: `Правка сохранена, но не синхронизирована с Telegram: ${updatedPost.telegramSyncError}`,
          variant: "error",
        });
      }
    },
  });
}

export function usePostTelegramSyncing(postId: string) {
  const accountId = useQueryAccountScope();
  const { data: posts = [] } = usePosts();
  const pendingMutationIds = useMutationState({
    filters: {
      mutationKey: queryKeys.posts.telegramSync(accountId),
      status: "pending",
    },
    select: (mutation) => mutation.state.variables as string,
  });
  const post = posts.find((item) => item.id === postId);
  return pendingMutationIds.includes(postId) || post?.telegramSyncPending === true;
}

export function usePublishPost() {
  const { posts } = useRepositories();
  const queryClient = useQueryClient();
  const accountId = useQueryAccountScope();

  return useMutation({
    mutationKey: queryKeys.posts.telegramSync(accountId),
    mutationFn: (id: string) => posts.publish(id),
    onSuccess: (updatedPost) => applyPostUpdate(queryClient, accountId, updatedPost),
  });
}

export function useSchedulePost() {
  const { posts } = useRepositories();
  const queryClient = useQueryClient();
  const accountId = useQueryAccountScope();

  return useMutation({
    mutationFn: ({ id, scheduledAt }: { id: string; scheduledAt: string }) =>
      posts.schedule(id, scheduledAt),
    onSuccess: (updatedPost) => applyPostUpdate(queryClient, accountId, updatedPost),
  });
}

export function useReorderPosts() {
  const { posts } = useRepositories();
  const queryClient = useQueryClient();
  const accountId = useQueryAccountScope();

  return useMutation({
    mutationFn: (nextPosts: Post[]) => posts.reorder(nextPosts),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.posts.all(accountId) });
    },
  });
}

export function useDeletePost() {
  const { posts } = useRepositories();
  const queryClient = useQueryClient();
  const accountId = useQueryAccountScope();

  return useMutation({
    mutationKey: queryKeys.posts.telegramSync(accountId),
    mutationFn: (id: string) => posts.remove(id),
    onSuccess: (_data, id) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.posts.all(accountId) });
      queryClient.removeQueries({ queryKey: queryKeys.posts.detail(accountId, id) });
    },
  });
}
