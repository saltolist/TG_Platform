"use client";

import { GlobalChatCardView, LocalChatCardView } from "@/screens/chats/ui/ChatListCards";
import type { ChatsScreenState } from "@/screens/chats/model/useChatsScreen";
import { ConnectChannelEmptyState } from "@/features/connect-channel";
import { EmptyState } from "@/shared/ui/empty-state";

type Props = {
  data: ChatsScreenState["data"];
  actions: Pick<ChatsScreenState["actions"], "openGChat" | "goToHref">;
};

function renderEmptyState(
  showConnectChannel: boolean,
  icon: string,
  message: string,
) {
  if (showConnectChannel) {
    return <ConnectChannelEmptyState feature="чатам" icon={icon} />;
  }
  return <EmptyState icon={icon} message={message} />;
}

export function ChatsList({ data, actions }: Props) {
  const { tab, globalChats, localChats, isLoading, showConnectChannel } = data;
  const { openGChat, goToHref } = actions;

  if (isLoading) {
    return (
      <div className="chats-scroll">
        <div className="chats-scroll-inner">
          <p className="screen-placeholder">Загрузка чатов…</p>
        </div>
      </div>
    );
  }

  return (
    <div className="chats-scroll">
      <div className="chats-scroll-inner">
        {tab === "all" ? (
          globalChats.length === 0 && localChats.length === 0 ? (
            renderEmptyState(showConnectChannel, "💬", "Нет чатов")
          ) : (
            <>
              {globalChats.map((c) => (
                <GlobalChatCardView key={c.id} chat={c} onOpen={openGChat} />
              ))}
              {localChats.map((row) => (
                <LocalChatCardView
                  key={`${row.postId}-${row.chatId}`}
                  row={row}
                  onNavigate={goToHref}
                />
              ))}
            </>
          )
        ) : (
          <>
            <div style={{ display: tab === "global" ? "" : "none" }}>
              {globalChats.length === 0 ? (
                renderEmptyState(showConnectChannel, "💬", "Нет глобальных чатов")
              ) : (
                globalChats.map((c) => (
                  <GlobalChatCardView key={c.id} chat={c} onOpen={openGChat} />
                ))
              )}
            </div>
            <div style={{ display: tab === "local" ? "" : "none" }}>
              {localChats.length === 0 ? (
                renderEmptyState(showConnectChannel, "📄", "Нет локальных чатов")
              ) : (
                localChats.map((row) => (
                  <LocalChatCardView
                    key={`${row.postId}-${row.chatId}`}
                    row={row}
                    onNavigate={goToHref}
                  />
                ))
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
