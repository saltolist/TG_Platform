"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

import { useComposer } from "@/app/model/store/composer-store";
import { useNavigationStore } from "@/app/model/store/navigation-store";
import { usePostNavigationStore } from "@/app/model/store/post-navigation-store";
import { usePost, useUpdatePost } from "@/entities/post";
import {
  flattenVisibleWithPaths,
  lastAssistantFlatIndex,
  normalizeBranchedHistory,
  visibleHistoryRevision,
} from "@/shared/lib/chatPaths";
import { postTitle } from "@/shared/lib/helpers";
import { isQueryBootstrapping } from "@/shared/lib/query/isQueryBootstrapping";
import { parseAppPath, routes } from "@/shared/lib/routes";
import { useChatThreadAutoScroll } from "@/shared/lib/hooks/useChatThreadAutoScroll";
import { useScreenBack } from "@/widgets/app-shell/model/useScreenBack";
import { usePostCtxMenuItems } from "@/features/post-context-menu";
import { useFeedPostLayout } from "@/widgets/feed";
import { usePostScreenHeader } from "./usePostScreenHeader";
import { useCompactHeader1000 } from "@/shared/lib/hooks/useCompactHeader1000";
import { useMobile760 } from "@/shared/lib/hooks/useMobile760";
import type { LocalNote, NoteListFilter, PostMedia, PostMode } from "@/shared/types";

export function usePostWorkspace() {
  const router = useRouter();
  const pathname = usePathname() ?? "/";
  const parsed = parseAppPath(pathname);
  const currentPostId = useNavigationStore((s) => s.currentPostId);
  const isEditing = useNavigationStore((s) => s.isEditing);
  const setNav = useNavigationStore((s) => s.setNav);
  const postId = currentPostId ?? parsed.postId;
  const postMode = usePostNavigationStore((s) =>
    postId != null ? s.getMode(postId) : "chat",
  );
  const currentPostChatId = usePostNavigationStore((s) =>
    postId != null ? s.getCurrentPostChatId(postId) : null,
  );
  const setMode = usePostNavigationStore((s) => s.setMode);
  const { sendPost } = useComposer();
  const updatePost = useUpdatePost();
  const handleBack = useScreenBack();

  const { data: post, isLoading, error } = usePost(postId ?? "");
  const { phoneFormat, layoutClassName, layoutStyle } = useFeedPostLayout();
  const isMobile = useMobile760();
  const postHeaderCompact1000 = useCompactHeader1000();

  const chatScrollRef = useRef<HTMLDivElement>(null);
  const postCardRef = useRef<HTMLDivElement>(null);

  const [listSearch, setListSearch] = useState("");
  const [listContextFilter, setListContextFilter] = useState<NoteListFilter>("all");

  const mediaItems: PostMedia[] = post?.media ?? [];
  const activeChat = post?.chats.find((c) => c.id === currentPostChatId) ?? null;
  const chatHistory = normalizeBranchedHistory(activeChat?.history ?? []);
  const chatHistoryRevision = visibleHistoryRevision(chatHistory);
  const flatMessages = flattenVisibleWithPaths(chatHistory);
  const lastAssistantFlat = lastAssistantFlatIndex(flatMessages);

  const syncPostUrl = useCallback(
    (mode: PostMode, chatId: string | null) => {
      if (postId == null) return;
      if (mode === "chat" && chatId != null) {
        router.replace(routes.post(postId, chatId));
      } else {
        router.replace(routes.post(postId));
      }
    },
    [postId, router],
  );

  const applyPostView = useCallback(
    (nextMode: PostMode, nextChatId: string | null = null) => {
      if (postId == null) return;
      setMode(postId, nextMode, nextChatId);
      setListSearch("");
      syncPostUrl(nextMode, nextMode === "chat" ? nextChatId : null);
    },
    [postId, setMode, syncPostUrl],
  );

  const goToPostNotes = useCallback(() => applyPostView("notes", null), [applyPostView]);
  const goToPostChats = useCallback(() => applyPostView("chats", null), [applyPostView]);
  const openPostView = useCallback(
    () => applyPostView("chat", currentPostChatId),
    [applyPostView, currentPostChatId],
  );
  const openLocalChat = useCallback(
    (chatId: string) => applyPostView("chat", chatId),
    [applyPostView],
  );
  const startNewChat = useCallback(() => applyPostView("chat", null), [applyPostView]);
  const startNewNote = useCallback(() => {
    if (!post) return;
    router.push(routes.noteNew("post", post.id));
  }, [post, router]);

  const navigateFeed = useCallback(() => {
    router.push(routes.feed());
  }, [router]);
  const resetToPostChatRoot = useCallback(() => {
    if (postId == null) return;
    setMode(postId, "chat", null);
    setListSearch("");
    router.replace(routes.post(postId));
    setNav({ isEditing: false });
  }, [postId, router, setMode, setNav]);
  const openComments = useCallback(() => applyPostView("comments", null), [applyPostView]);

  const { items: ctxItems, modal: ctxModal } = usePostCtxMenuItems(post, {
    onNewChat: startNewChat,
    onNewNote: startNewNote,
  });

  const postHeader = usePostScreenHeader({
    post: post ?? null,
    postMode,
    currentPostChatId,
    activeChat,
    isMobile,
    postHeaderCompact1000,
    ctxItems,
    listSearch,
    setListSearch,
    chatScrollRef,
    postCardRef,
    openPostView,
    goToPostNotes,
    goToPostChats,
  });

  const startEdit = useCallback(() => {
    setNav({ isEditing: true });
  }, [setNav]);

  const cancelEdit = useCallback(() => {
    setNav({ isEditing: false });
  }, [setNav]);

  const savePost = useCallback(
    (text: string, media: PostMedia[]) => {
      if (!post) return;
      void updatePost.mutateAsync({
        id: post.id,
        patch: { text, media: media.length > 0 ? [...media] : undefined },
      });
      setNav({ isEditing: false });
    },
    [post, setNav, updatePost],
  );

  const openNote = useCallback(
    (note: LocalNote) => {
      if (!post) return;
      router.push(routes.notePost(post.id, note.id));
    },
    [post, router],
  );

  const toggleNoteAi = useCallback(
    (noteId: string) => {
      if (!post) return;
      const notes = post.notes.map((n) =>
        n.id === noteId ? { ...n, ai: !n.ai } : n,
      );
      void updatePost.mutateAsync({ id: post.id, patch: { notes } });
    },
    [post, updatePost],
  );

  useChatThreadAutoScroll(
    chatScrollRef,
    flatMessages.length,
    chatHistoryRevision,
    postMode === "chat",
  );

  useEffect(() => {
    setListContextFilter("all");
  }, [post?.id]);

  const headerTitle = post ? postTitle(post) : "Пост";

  return {
    isLoading: isQueryBootstrapping(isLoading, post),
    error,
    data: {
      post: post ?? null,
      postMode,
      isEditing,
      currentPostChatId,
      activeChat,
      flatMessages,
      lastAssistantFlat,
      mediaItems,
    },
    ui: {
      phoneFormat,
      layoutClassName,
      layoutStyle,
      listSearch,
      setListSearch,
      listContextFilter,
      setListContextFilter,
      headerTitle,
      chatScrollRef,
      postCardRef,
      postHeader,
      ctxItems,
      ctxModal,
      isMobile,
    },
    actions: {
      goToPostNotes,
      goToPostChats,
      openPostView,
      openLocalChat,
      startNewChat,
      startNewNote,
      navigateFeed,
      resetToPostChatRoot,
      handleBack,
      startEdit,
      cancelEdit,
      savePost,
      openComments,
      openNote,
      toggleNoteAi,
      sendPost,
    },
  };
}

export type PostWorkspace = ReturnType<typeof usePostWorkspace>;
