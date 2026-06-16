"use client";

import { useMemo } from "react";

import { filterPostComments, findPostComment } from "@/shared/lib/postComments";
import type { PostComment } from "@/shared/types";

import PostCommentRow from "./PostCommentRow";
import PostCommentsRow from "./PostCommentsRow";

type Props = {
  comments: PostComment[];
  search?: string;
  onOpenComments?: () => void;
  onReply?: (comment: PostComment) => void;
  emptyHint?: string;
};

export default function PostCardCommentsSection({
  comments,
  search = "",
  onOpenComments,
  onReply,
  emptyHint = "Пока нет комментариев — напишите первый",
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
              onReply={onReply ? () => onReply(c) : undefined}
            />
          ))}
        </div>
      )}
    </>
  );
}
