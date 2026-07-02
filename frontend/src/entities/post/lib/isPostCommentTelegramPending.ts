import type { PostComment } from "@/shared/types";

/** Platform comment not yet confirmed in Telegram discussion group. */
export function isPostCommentTelegramPending(
  comment: PostComment,
  postTelegramLinked: boolean,
): boolean {
  return postTelegramLinked && !comment.telegramMessageId;
}
