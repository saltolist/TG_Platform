"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/shared/api/queryKeys";
import { useRepositories } from "@/app/providers/RepositoryProvider";
import { useAuthenticatedQueryEnabled } from "@/app/providers/useAuthenticatedQueryEnabled";
import { useQueryAccountScope } from "@/app/providers/useQueryAccountScope";
import type { Post } from "@/shared/types";

export function usePosts() {
  const { posts } = useRepositories();
  const enabled = useAuthenticatedQueryEnabled();
  const accountId = useQueryAccountScope();

  return useQuery({
    queryKey: queryKeys.posts.list(accountId),
    queryFn: () => posts.list(),
    enabled,
    placeholderData: (previous) => previous,
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
      const cached = queryClient.getQueryData<Post>(queryKeys.posts.detail(accountId, id));
      if (cached) return cached;
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
      queryClient.setQueryData(queryKeys.posts.detail(accountId, updatedPost.id), updatedPost);
      queryClient.setQueryData<Post[]>(queryKeys.posts.list(accountId), (prev) =>
        prev?.map((p) => (p.id === updatedPost.id ? updatedPost : p)),
      );
    },
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
    mutationFn: (id: string) => posts.remove(id),
    onSuccess: (_data, id) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.posts.all(accountId) });
      queryClient.removeQueries({ queryKey: queryKeys.posts.detail(accountId, id) });
    },
  });
}
