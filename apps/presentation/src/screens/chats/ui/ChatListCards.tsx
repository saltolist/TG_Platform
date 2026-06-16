"use client";

import { GlobalChatCard, LocalChatCard, type LocalChatRow } from "@/entities/chat/ui/ChatCards";
import { chatListAssistantLine, chatListUserLine, formatStoredDate } from "@/shared/lib/helpers";
import { isOmnichannelChat } from "@/shared/lib/omnichannel";
import { routes } from "@/shared/lib/routes";
import { NavIconChats, NavIconFeed, NavIconSend } from "@/shared/ui/nav-icons";
import type { GlobalChat } from "@/shared/types";
import ChatListCardMenu from "@/widgets/chat-thread/ui/ChatListCardMenu";

type GlobalProps = {
  chat: GlobalChat;
  onOpen: (id: string) => void;
};

export function GlobalChatCardView({ chat, onOpen }: GlobalProps) {
  const userLine = chatListUserLine(chat.history, chat.title);
  const assistantLine = chatListAssistantLine(chat.history, chat.preview);
  const omnichannel = isOmnichannelChat(chat);

  return (
    <GlobalChatCard
      userLine={userLine}
      assistantLine={assistantLine}
      date={formatStoredDate(chat.date)}
      onOpen={() => onOpen(chat.id)}
      iconRail={
        omnichannel ? <NavIconSend strokeWidth={1.5} /> : <NavIconChats strokeWidth={1.5} />
      }
      menu={<ChatListCardMenu scope="global" chatId={chat.id} title={chat.title} />}
    />
  );
}

type LocalProps = {
  row: LocalChatRow;
  onNavigate: (href: string) => void;
};

export function LocalChatCardView({ row, onNavigate }: LocalProps) {
  const userLine = chatListUserLine(row.history, row.title);
  const assistantLine = chatListAssistantLine(row.history, row.preview);

  return (
    <LocalChatCard
      userLine={userLine}
      assistantLine={assistantLine}
      date={formatStoredDate(row.date)}
      titleAttr={`Пост: ${row.postTitle}`}
      onOpen={() => onNavigate(routes.post(row.postId, row.chatId))}
      iconRail={<NavIconFeed strokeWidth={1.5} outerStrokeWidth={1.5} />}
      menu={
        <ChatListCardMenu
          scope="local"
          postId={row.postId}
          chatId={row.chatId}
          title={row.title}
        />
      }
    />
  );
}
