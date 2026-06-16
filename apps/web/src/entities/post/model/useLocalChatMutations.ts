"use client";

import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useRepositories } from "@/app/providers/RepositoryProvider";
import { assistantPlainText } from "@/entities/message";
import { getCachedPost, setCachedPost } from "@/entities/post/lib/getCachedPost";
import { fetchPost, patchPostChatHistory } from "@/entities/post/lib/patchPostChatHistory";
import { queryKeys } from "@/shared/api/queryKeys";
import { appendToActiveHistory } from "@/shared/lib/chatPaths";
import type { ChatMessage, LocalChat } from "@/shared/types";

import { useUpdatePost } from "./usePosts";

function previewForMessage(message: ChatMessage): string | undefined {
  const text = assistantPlainText(message).trim();
  if (!text) return undefined;
  return text.slice(0, 80);
}

export function useAddLocalChat() {
  const { posts } = useRepositories();
  const updatePost = useUpdatePost();
  const queryClient = useQueryClient();

  return useCallback(
    async (postId: string, chat: LocalChat) => {
      const post = await fetchPost(queryClient, posts, postId);
      const updated = { ...post, chats: [...post.chats, chat] };
      await updatePost.mutateAsync({ id: postId, patch: { chats: updated.chats } });
      setCachedPost(queryClient, updated);
    },
    [posts, queryClient, updatePost],
  );
}

export function usePushLocalChatMessage() {
  const { posts } = useRepositories();
  const queryClient = useQueryClient();

  return useCallback(
    async (postId: string, chatId: string, message: ChatMessage) => {
      await patchPostChatHistory(
        queryClient,
        posts,
        postId,
        chatId,
        (history) => appendToActiveHistory(history, message),
        { preview: previewForMessage(message) },
      );
    },
    [posts, queryClient],
  );
}

export function useRenameLocalChat() {
  const updatePost = useUpdatePost();
  const queryClient = useQueryClient();

  return useCallback(
    async (postId: string, chatId: string, title: string) => {
      const post = getCachedPost(queryClient, postId);
      if (!post) return;
      const chats = post.chats.map((chat) =>
        chat.id === chatId ? { ...chat, title } : chat,
      );
      const updated = { ...post, chats };
      await updatePost.mutateAsync({ id: postId, patch: { chats } });
      setCachedPost(queryClient, updated);
    },
    [queryClient, updatePost],
  );
}

export function useDeleteLocalChat() {
  const updatePost = useUpdatePost();
  const queryClient = useQueryClient();

  return useCallback(
    async (postId: string, chatId: string) => {
      const post = getCachedPost(queryClient, postId);
      if (!post) return;
      const chats = post.chats.filter((chat) => chat.id !== chatId);
      const updated = { ...post, chats };
      await updatePost.mutateAsync({ id: postId, patch: { chats } });
      setCachedPost(queryClient, updated);
    },
    [queryClient, updatePost],
  );
}
