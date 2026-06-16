"use client";

import { MessageSquare } from "lucide-react";

import { EmptyState } from "@/shared/ui/empty-state";
import { Composer } from "@/widgets/composer";
import { ScreenShell } from "@/screens/_ui/screen-shell";
import { useGChatScreen } from "@/screens/gchat/model/useGChatScreen";
import { GChatScreenHeader } from "@/screens/gchat/ui/GChatScreenHeader";
import { GlobalChatMessages } from "@/screens/gchat/ui/GlobalChatMessages";

export function GChatScreen() {
  const {
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
  } = useGChatScreen();

  const header = (
    <GChatScreenHeader
      chatTitle={chat?.title ?? ""}
      omnichannel={omnichannel}
      showDelete={Boolean(chat)}
      onNavigateBackToChats={navigateBackToChats}
      onDeleteChat={handleDeleteChat}
    />
  );

  if (!gchatId) {
    return (
      <ScreenShell header={header}>
        <EmptyState
          icon={<MessageSquare className="size-5" />}
          message="Укажите чат: /gchat/?id=gc1"
          className="min-h-[50vh]"
        />
      </ScreenShell>
    );
  }

  if (isLoading) {
    return (
      <ScreenShell header={header}>
        <EmptyState icon={<MessageSquare className="size-5" />} message="Загрузка чата…" />
      </ScreenShell>
    );
  }

  if (error || !chat) {
    return (
      <ScreenShell header={header}>
        <EmptyState
          icon={<MessageSquare className="size-5" />}
          message={error?.message ?? "Чат не найден"}
        />
      </ScreenShell>
    );
  }

  return (
    <>
      {header}
      <div className="gchat-layout">
        <GlobalChatMessages
          chatId={gchatId}
          flatMessages={flatMessages}
          lastAssistantFlat={lastAssistantFlat}
          messagesRef={messagesRef}
        />
        <Composer scope="gchat" onSubmit={sendGChat} />
      </div>
    </>
  );
}
