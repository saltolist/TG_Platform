import { chatListAssistantLine, chatListUserLine, postTitle } from "@/shared/lib/helpers";
import type { LocalChatRow } from "@/entities/chat/ui/ChatCards";
import type { GlobalChat, Post } from "@/shared/types";

export function normalizeChatSearchQuery(query: string): string {
  return query.trim().toLowerCase();
}

export function globalChatMatchesSearch(chat: GlobalChat, query: string): boolean {
  const q = normalizeChatSearchQuery(query);
  if (!q) return true;
  const u = chatListUserLine(chat.history, chat.title);
  const a = chatListAssistantLine(chat.history, chat.preview);
  return `${u} ${a}`.toLowerCase().includes(q);
}

export function filterGlobalChats(chats: GlobalChat[], query: string): GlobalChat[] {
  return chats.filter((c) => globalChatMatchesSearch(c, query));
}

export function buildLocalChatRows(posts: Post[]): LocalChatRow[] {
  return posts.flatMap((p) =>
    p.chats.map<LocalChatRow>((c) => ({
      postId: p.id,
      postTitle: postTitle(p),
      chatId: c.id,
      title: c.title || "Без названия",
      preview: c.preview || "",
      date: c.date || "",
      history: c.history,
    })),
  );
}

export function localChatRowMatchesSearch(row: LocalChatRow, query: string): boolean {
  const q = normalizeChatSearchQuery(query);
  if (!q) return true;
  const u = chatListUserLine(row.history, row.title);
  const a = chatListAssistantLine(row.history, row.preview);
  return `${u} ${a} ${row.postTitle}`.toLowerCase().includes(q);
}

export function filterLocalChatRows(rows: LocalChatRow[], query: string): LocalChatRow[] {
  return rows.filter((row) => localChatRowMatchesSearch(row, query));
}
