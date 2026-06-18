"use client";

import { GlobalChatCardView, LocalChatCardView } from "@/screens/chats/ui/ChatListCards";
import type { ChatsScreenState } from "@/screens/chats/model/useChatsScreen";
import { EmptyState } from "@/shared/ui/empty-state";

type Props = {
  data: ChatsScreenState["data"];
  actions: Pick<ChatsScreenState["actions"], "openGChat" | "goToHref">;
};

export function ChatsList({ data, actions }: Props) {
  const { tab, globalChats, localChats, isLoading } = data;
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
            <EmptyState icon="💬" message="Нет чатов" />
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
                <EmptyState icon="💬" message="Нет глобальных чатов" />
              ) : (
                globalChats.map((c) => (
                  <GlobalChatCardView key={c.id} chat={c} onOpen={openGChat} />
                ))
              )}
            </div>
            <div style={{ display: tab === "local" ? "" : "none" }}>
              {localChats.length === 0 ? (
                <EmptyState icon="📄" message="Нет локальных чатов" />
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
