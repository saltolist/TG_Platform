"use client";

import { ChatListCardMenu } from "@/widgets/chat-thread";
import { EmptyState } from "@/shared/ui/empty-state";
import { chatListAssistantLine, chatListUserLine, formatStoredDate } from "@/shared/lib/helpers";
import type { Post } from "@/shared/types";

type Props = {
  post: Post;
  search: string;
  onOpenChat: (chatId: string) => void;
};

export default function PostChatsList({ post, search, onOpenChat }: Props) {
  const q = search.trim().toLowerCase();
  const chats = post.chats.filter((c) => {
    if (!q) return true;
    const u = chatListUserLine(c.history, c.title || "Без названия");
    const a = chatListAssistantLine(c.history, c.preview || "");
    return `${u} ${a} ${c.title}`.toLowerCase().includes(q);
  });

  return (
    <div id="post-chats" className="post-chats visible">
      <div className="post-chats-inner">
        {post.chats.length === 0 ? (
          <EmptyState icon="💬" message="Пока нет локальных чатов" />
        ) : chats.length === 0 ? (
          <EmptyState icon="💬" message="Ничего не найдено" />
        ) : (
          chats.map((c) => {
            const userLine = chatListUserLine(c.history, c.title || "Без названия");
            const assistantLine = chatListAssistantLine(c.history, c.preview || "");
            return (
              <div key={c.id} className="chat-card" onClick={() => onOpenChat(c.id)}>
                <div className="chat-card-body-row">
                  <div className="chat-card-main">
                    <div className="chat-card-row1">
                      <div className="chat-card-title">{userLine}</div>
                      <div className="chat-card-menu-slot" onClick={(e) => e.stopPropagation()}>
                        <ChatListCardMenu
                          scope="local"
                          postId={post.id}
                          chatId={c.id}
                          title={c.title || "Без названия"}
                        />
                      </div>
                    </div>
                    <div className="chat-card-row2">
                      <div className="chat-card-preview">{assistantLine || "—"}</div>
                      <div className="chat-card-date">{formatStoredDate(c.date)}</div>
                    </div>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
