"use client";

import { useRouter } from "next/navigation";
import { useMemo } from "react";

import { useNavigationStore } from "@/app/model/store";
import {
  buildLocalChatRows,
  filterGlobalChats,
  filterLocalChatRows,
} from "@/entities/chat/lib/chatList";
import { useGlobalChats } from "@/entities/chat";
import { useChannelConnected } from "@/entities/channel";
import { usePosts } from "@/entities/post";
import { useMobile760 } from "@/shared/lib/hooks/useMobile760";
import { isListQueryBootstrapping } from "@/shared/lib/query/isQueryBootstrapping";
import { routes } from "@/shared/lib/routes";
import type { ChatsTab } from "@/shared/types";

export function useChatsScreen() {
  const router = useRouter();
  const isMobile = useMobile760();
  const tab = useNavigationStore((s) => s.chatsTab);
  const search = useNavigationStore((s) => s.chatsSearch);

  const { data: globalChatsSource = [], isLoading: globalLoading } = useGlobalChats();
  const { data: posts = [], isLoading: postsLoading } = usePosts();
  const { isConnected: isChannelConnected, isLoading: isChannelLoading } = useChannelConnected();

  const localChatsSource = useMemo(() => buildLocalChatRows(posts), [posts]);
  const hasAnyChats = globalChatsSource.length > 0 || localChatsSource.length > 0;
  const showConnectChannel =
    !isChannelLoading && !isChannelConnected && !search.trim() && !hasAnyChats;

  const globalChats = useMemo(
    () => filterGlobalChats(globalChatsSource, search),
    [globalChatsSource, search],
  );

  const localChats = useMemo(
    () => filterLocalChatRows(localChatsSource, search),
    [localChatsSource, search],
  );

  return {
    data: {
      tab,
      globalChats,
      localChats,
      isLoading:
        isListQueryBootstrapping(globalLoading, globalChatsSource) ||
        isListQueryBootstrapping(postsLoading, posts),
      showConnectChannel,
    },
    ui: {
      isMobile,
    },
    actions: {
      openGChat: (id: string) => router.push(routes.gchat(id)),
      goToHref: (href: string) => router.push(href),
      setTab: (t: ChatsTab) => useNavigationStore.getState().setChatsTab(t),
    },
  };
}

export type ChatsScreenState = ReturnType<typeof useChatsScreen>;
