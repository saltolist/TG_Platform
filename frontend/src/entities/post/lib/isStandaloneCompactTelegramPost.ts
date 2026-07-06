import { getPostMediaItems, isCompactMediaKind } from "@/shared/lib/helpers";
import type { Post } from "@/shared/types";

/** Telegram sticker / video-note post without a caption — not a text post on the platform. */
export function isStandaloneCompactTelegramPost(post: Post): boolean {
  if (!post.telegramMessageId) return false;

  const media = getPostMediaItems(post);
  if (media.length === 0) return false;

  const hasText = Boolean(post.text?.trim() || post.textHtml?.trim());
  if (hasText) return false;

  return media.every((item) => isCompactMediaKind(item));
}

/** Whether copy/edit toolbar and platform text edits are allowed for this post. */
export function postSupportsPlatformEdit(post: Post): boolean {
  if (post.status === "draft" || post.status === "scheduled") return true;
  return !isStandaloneCompactTelegramPost(post);
}
