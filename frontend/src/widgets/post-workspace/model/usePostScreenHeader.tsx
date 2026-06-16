"use client";

import { useCallback, useEffect, useState, type RefObject } from "react";

import { postTitle } from "@/shared/lib/helpers";
import { getPostListSearchPlaceholder, getPostSubPageLabel } from "@/shared/lib/post/postHeader";
import type { CtxMenuItem } from "@/shared/ui/context-menu";
import type { PageHeaderOverflowItem } from "@/widgets/page-header";
import { NavIconChats, NavIconFeed, NavIconNotes } from "@/shared/ui/nav-icons";
import type { LocalChat, Post, PostMode } from "@/shared/types";

type Args = {
  post: Post | null;
  postMode: PostMode;
  currentPostChatId: string | null;
  activeChat: LocalChat | null;
  isMobile: boolean;
  postHeaderCompact1000: boolean;
  ctxItems: CtxMenuItem[];
  listSearch: string;
  setListSearch: (value: string) => void;
  chatScrollRef: RefObject<HTMLDivElement | null>;
  postCardRef: RefObject<HTMLDivElement | null>;
  openPostView: () => void;
  goToPostNotes: () => void;
  goToPostChats: () => void;
};

export function usePostScreenHeader({
  post,
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
}: Args) {
  const [showJump, setShowJump] = useState(false);

  const scrollToPost = useCallback(() => {
    document.getElementById("post-chat-scroll")?.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  const postSubPage = getPostSubPageLabel(postMode);
  const showListHeaderSearch = postSubPage != null;
  const listSearchPlaceholder = getPostListSearchPlaceholder(postMode);
  const postIntermediateCrumb = post ? postTitle(post) : "";

  useEffect(() => {
    if (postMode !== "chat") {
      setShowJump(false);
      return;
    }
    const sync = () => {
      if (!chatScrollRef.current || !postCardRef.current) return;
      const hdr = chatScrollRef.current
        .closest(".screen")
        ?.querySelector<HTMLElement>(".page-header--post");
      const revealLine =
        hdr?.getBoundingClientRect().bottom ??
        chatScrollRef.current.getBoundingClientRect().top;
      const cr = postCardRef.current.getBoundingClientRect();
      setShowJump(cr.bottom < revealLine + 4);
    };
    sync();
    const el = chatScrollRef.current;
    el?.addEventListener("scroll", sync, { passive: true });
    window.addEventListener("resize", sync);
    return () => {
      el?.removeEventListener("scroll", sync);
      window.removeEventListener("resize", sync);
    };
  }, [postMode, post?.id, activeChat?.id, chatScrollRef, postCardRef]);

  const postHeaderOverflowItems: PageHeaderOverflowItem[] = !post
    ? []
    : [
        ...(postMode === "chat" && showJump
          ? [
              {
                label: "↑ К посту",
                icon: <NavIconFeed />,
                onClick: scrollToPost,
              },
            ]
          : []),
        ...(postMode !== "chat"
          ? [
              {
                label: "К посту",
                onClick: openPostView,
                icon: <NavIconFeed />,
              },
            ]
          : []),
        {
          label: "Заметки",
          onClick: goToPostNotes,
          active: postMode === "notes",
          icon: <NavIconNotes />,
        },
        {
          label: "Чаты",
          onClick: goToPostChats,
          active: postMode === "chats",
          icon: <NavIconChats />,
        },
        ...ctxItems.map((item) => ({
          label: item.label,
          onClick: item.onClick,
          icon: item.icon,
          danger: item.danger,
          disabled: item.disabled,
        })),
      ];

  const showPostModeButtons = !postHeaderCompact1000;
  const overflowCount = postHeaderOverflowItems.length;
  const showPostTabletOverflow = postHeaderCompact1000 && !isMobile && overflowCount > 0;

  return {
    postSubPage,
    showListHeaderSearch,
    listSearchPlaceholder,
    postIntermediateCrumb,
    showJump,
    postHeaderOverflowItems,
    showPostModeButtons,
    showPostTabletOverflow,
    scrollToPost,
    listSearch,
    setListSearch,
    postMode,
    currentPostChatId,
    activeChat,
  };
}

export type PostScreenHeaderState = ReturnType<typeof usePostScreenHeader>;
