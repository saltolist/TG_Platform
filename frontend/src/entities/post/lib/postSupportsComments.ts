import type { Post } from "@/shared/types";

/** Fresh live-sync / catch-up posts may appear before per-post flags are persisted. */
const RECENT_TELEGRAM_POST_MS = 10 * 60 * 1000;

function isRecentTelegramPost(post: Post): boolean {
  if (post.status !== "published" || !post.telegramMessageId) return false;
  const raw = post.date;
  if (!raw) return false;
  const publishedAt = Date.parse(raw);
  if (Number.isNaN(publishedAt)) return false;
  return Date.now() - publishedAt < RECENT_TELEGRAM_POST_MS;
}

/** Whether this post can show the comments UI (per-post TG discussion thread). */
export function postSupportsComments(
  post: Post,
  channelCommentsEnabled: boolean,
): boolean {
  if (!channelCommentsEnabled) return false;
  if (post.status !== "published") return false;
  if (post.commentsThreadAvailable === false) return false;

  const channelMsgId = post.telegramMessageId;
  const rootId = post.telegramDiscussionMessageId;
  if (rootId && channelMsgId) {
    if (rootId === channelMsgId) return false;
    return true;
  }

  if (post.commentsThreadLiveOptimistic === true) return true;
  if (isRecentTelegramPost(post)) return true;

  return false;
}
