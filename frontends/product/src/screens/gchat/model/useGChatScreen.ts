"use client";

import { useCallback, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { useComposer } from "@/app/model/store/composer-store";
import { useGlobalChat } from "@/entities/chat";
import { useDeleteChat } from "@/features/delete-chat";
import {
  flattenVisibleWithPaths,
  lastAssistantFlatIndex,
  normalizeBranchedHistory,
  visibleHistoryRevision,
} from "@/shared/lib/chatPaths";
import { useChatThreadAutoScroll } from "@/shared/lib/hooks/useChatThreadAutoScroll";
import { isOmnichannelChat, isOmnichannelChatId } from "@/shared/lib/omnichannel";
import { parseGChatSearchParam, routes } from "@/shared/lib/routes";

export function useGChatScreen() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const gchatId = parseGChatSearchParam(searchParams.get("id"));
  const { data: chat, isLoading, error } = useGlobalChat(gchatId);
  const { sendGChat } = useComposer();
  const deleteChat = useDeleteChat();
  const messagesRef = useRef<HTMLDivElement>(null);
  const omnichannel = chat ? isOmnichannelChat(chat) : isOmnichannelChatId(gchatId);

  const navigateBackToChats = useCallback(() => {
    router.push(routes.chats());
  }, [router]);

  const handleDeleteChat = useCallback(() => {
    if (!chat || !gchatId) return;
    deleteChat({ scope: "global", chatId: gchatId, title: chat.title });
  }, [chat, deleteChat, gchatId]);

  const history = normalizeBranchedHistory(chat?.history ?? []);
  const historyRevision = visibleHistoryRevision(history);
  const flatMessages = flattenVisibleWithPaths(history);
  const lastAssistantFlat = lastAssistantFlatIndex(flatMessages);

  useChatThreadAutoScroll(messagesRef, flatMessages.length, historyRevision);

  return {
    gchatId,
    chat,
    isLoading,
    error,
    omnichannel,
    flatMessages,
    lastAssistantFlat,
    messagesRef,
    sendGChat,
    navigateBackToChats,
    handleDeleteChat,
  };
}
