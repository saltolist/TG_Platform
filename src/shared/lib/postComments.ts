import type { PostComment } from "@/shared/types";

export function filterPostComments(comments: PostComment[], query: string): PostComment[] {
  const q = query.trim().toLowerCase();
  if (!q) return comments;
  return comments.filter(
    (c) => c.text.toLowerCase().includes(q) || c.author.toLowerCase().includes(q),
  );
}

export function findPostComment(comments: PostComment[], id: string): PostComment | undefined {
  return comments.find((c) => c.id === id);
}

export function avatarHue(name: string): number {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h + name.charCodeAt(i) * 17) % 360;
  return h;
}

export function avatarInitials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return name.slice(0, 2).toUpperCase();
}
