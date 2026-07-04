import type { PostComment } from "@/shared/types";

import { isPlatformSelfComment, PLATFORM_SELF_COMMENT_AUTHOR } from "@/shared/lib/postComments";

export type CommentDeleteTombstone = {
  comment: PostComment;
  /** Index in the list at the moment the user triggered delete. */
  index: number;
};

/** Keep optimistic platform comments when a background poll returns a stale snapshot. */
export function mergePostCommentsFromServer(
  localComments: PostComment[] | undefined,
  serverComments: PostComment[] | undefined,
): PostComment[] {
  const server = serverComments ?? [];
  const local = localComments ?? [];
  if (local.length === 0) return server;

  const serverById = new Map(server.map((comment) => [comment.id, comment]));
  const localById = new Map(local.map((comment) => [comment.id, comment]));
  const localByTelegramId = new Map(
    local
      .filter((comment) => comment.telegramMessageId)
      .map((comment) => [comment.telegramMessageId!, comment]),
  );

  const merged = server.map((serverComment) => {
    const localMatch =
      localById.get(serverComment.id) ??
      (serverComment.telegramMessageId
        ? localByTelegramId.get(serverComment.telegramMessageId)
        : undefined);
    if (localMatch && isPlatformSelfComment(localMatch.author)) {
      return { ...serverComment, author: PLATFORM_SELF_COMMENT_AUTHOR };
    }
    return serverComment;
  });

  for (const comment of local) {
    if (serverById.has(comment.id)) continue;
    if (!comment.telegramMessageId) {
      merged.push(comment);
    }
  }

  return merged;
}

/** Keep deleted rows in their original slot while Telegram confirms the delete. */
export function mergeCommentsWithDeleteTombstones(
  comments: PostComment[],
  syncingDeleteById: ReadonlyMap<string, CommentDeleteTombstone>,
): PostComment[] {
  if (syncingDeleteById.size === 0) return comments;

  const serverIds = new Set(comments.map((comment) => comment.id));
  const tombstones = [...syncingDeleteById.values()].filter(
    ({ comment }) => !serverIds.has(comment.id),
  );
  if (tombstones.length === 0) return comments;

  const sorted = [...tombstones].sort((left, right) => left.index - right.index);

  const result = [...comments];
  const nextInsertAtByIndex = new Map<number, number>();
  for (const { comment, index } of sorted) {
    const insertAt =
      nextInsertAtByIndex.get(index) ?? Math.max(0, Math.min(index, result.length));
    result.splice(insertAt, 0, comment);
    nextInsertAtByIndex.set(index, insertAt + 1);
  }
  return result;
}
