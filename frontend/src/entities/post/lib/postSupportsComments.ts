import type { Post } from "@/shared/types";

function hasConfirmedDiscussionRoot(post: Post): boolean {
  const channelMsgId = post.telegramMessageId;
  const rootId = post.telegramDiscussionMessageId;
  if (!channelMsgId || !rootId) return false;
  return rootId !== channelMsgId;
}

/** Whether this post can show the comments UI (per-post TG discussion thread). */
export function postSupportsComments(
  post: Post,
  channelCommentsEnabled: boolean,
): boolean {
  if (!channelCommentsEnabled) return false;
  if (post.status !== "published") return false;
  if (post.commentsThreadAvailable === false) return false;
  return hasConfirmedDiscussionRoot(post);
}
