"use client";

import { useMemo } from "react";

import { filterPostComments, findPostComment } from "@/shared/lib/postComments";
import { isPostCommentTelegramPending } from "@/entities/post/lib/isPostCommentTelegramPending";
import type { PostComment } from "@/shared/types";

import PostCommentRow from "./PostCommentRow";
import PostCommentsRow from "./PostCommentsRow";

type Props = {
  comments: PostComment[];
  search?: string;
  onOpenComments?: () => void;
  onReply?: (comment: PostComment) => void;
  emptyHint?: string;
  postTelegramLinked?: boolean;
};

export default function PostCardCommentsSection({
  comments,
  search = "",
  onOpenComments,
  onReply,
  emptyHint = "Пока нет комментариев — напишите первый",
  postTelegramLinked = false,
}: Props) {
  const filtered = useMemo(() => filterPostComments(comments, search), [comments, search]);

  return (
    <>
      <PostCommentsRow
        count={comments.length}
        onClick={
          onOpenComments
            ? (e) => {
                e.stopPropagation();
                onOpenComments();
              }
            : undefined
        }
      />
      {filtered.length === 0 ? (
        <div className="post-comments-empty">
          {search.trim() ? "Ничего не найдено" : emptyHint}
        </div>
      ) : (
        <div className="post-comments-list">
          {filtered.map((c) => (
            <PostCommentRow
              key={c.id}
              comment={c}
              parent={c.replyToId ? findPostComment(comments, c.replyToId) : undefined}
              telegramSyncing={isPostCommentTelegramPending(c, postTelegramLinked)}
              onReply={onReply ? () => onReply(c) : undefined}
            />
          ))}
        </div>
      )}
    </>
  );
}
