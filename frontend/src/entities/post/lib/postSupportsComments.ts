import type { Post } from "@/shared/types";

/** Whether this post can show the comments UI (per-post TG discussion thread). */
export function postSupportsComments(
  post: Post,
  channelCommentsEnabled: boolean,
): boolean {
  if (!channelCommentsEnabled) return false;
  if (post.status !== "published") return false;
  if (post.commentsThreadAvailable === false) return false;
  return post.commentsThreadAvailable === true || Boolean(post.telegramDiscussionMessageId);
}
