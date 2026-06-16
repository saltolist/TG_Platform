import type { PostMode } from "@/shared/types";

export function getPostSubPageLabel(postMode: PostMode): string | null {
  if (postMode === "comments") return "Комментарии";
  if (postMode === "notes") return "Заметки";
  if (postMode === "chats") return "Чаты";
  return null;
}

export function getPostListSearchPlaceholder(postMode: PostMode): string {
  if (postMode === "comments") return "Поиск по комментариям...";
  if (postMode === "notes") return "Поиск по заметкам...";
  return "Поиск по чатам...";
}
