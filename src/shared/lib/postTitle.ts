import type { Post } from "@/shared/types";

export function postTitle(post: Pick<Post, "text">): string {
  const text = post.text?.trim() ?? "";
  if (!text) return "Без названия";
  const firstLine = text.split("\n")[0] ?? "";
  return firstLine.length > 60 ? `${firstLine.slice(0, 60)}…` : firstLine;
}
