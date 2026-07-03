"use client";

import { PostMediaBlock } from "@/entities/post";
import { PostTelegramSyncLabel } from "@/entities/post/ui/PostTelegramSyncLabel";
import { formatStoredDate, isVideoNoteKind } from "@/shared/lib/helpers";
import { avatarHue, avatarInitials } from "@/shared/lib/postComments";
import type { PostComment } from "@/shared/types";

import { PostCommentActions } from "./PostCommentActions";

type Props = {
  comment: PostComment;
  parent?: PostComment;
  onReply?: () => void;
  onDelete?: () => void;
  isDeleting?: boolean;
  telegramSyncing?: boolean;
};

export default function PostCommentRow({
  comment,
  parent,
  onReply,
  onDelete,
  isDeleting = false,
  telegramSyncing = false,
}: Props) {
  const hue = avatarHue(comment.author);
  const videoNoteMedia =
    comment.media?.length === 1 && comment.media[0] != null && isVideoNoteKind(comment.media[0]);
  const showSyncLabel = telegramSyncing || isDeleting;
  const showActions = Boolean(onReply || onDelete) && !isDeleting && !showSyncLabel;

  return (
    <article className={`post-comment${parent ? " post-comment--reply" : ""}`}>
      <div
        className="post-comment-avatar"
        style={{ background: showSyncLabel ? "var(--surface2)" : `hsl(${hue} 42% 38%)` }}
        aria-hidden
      >
        {showSyncLabel ? "↻" : avatarInitials(comment.author)}
      </div>
      <div className="post-comment-main">
        <div className="post-comment-head">
          {showSyncLabel ? (
            <PostTelegramSyncLabel className="post-comment-sync-label" />
          ) : (
            <span className="post-comment-author">{comment.author}</span>
          )}
          <span className="post-comment-date">{formatStoredDate(comment.date)}</span>
        </div>
        {parent ? (
          <div className="post-comment-quote">
            <span className="post-comment-quote-author">{parent.author}</span>
            <span className="post-comment-quote-text">{parent.text}</span>
          </div>
        ) : null}
        {comment.media && comment.media.length > 0 ? (
          videoNoteMedia ? (
            <div className="post-comment-video-note">
              <div className="post-comment-media post-comment-media--video-note">
                <PostMediaBlock media={comment.media} />
              </div>
              {showActions ? (
                <PostCommentActions
                  className="post-comment-actions--video-note"
                  onReply={onReply}
                  onDelete={onDelete}
                />
              ) : null}
            </div>
          ) : (
            <div className="post-comment-media">
              <PostMediaBlock media={comment.media} />
            </div>
          )
        ) : null}
        {comment.text ? <p className="post-comment-text">{comment.text}</p> : null}
        {showActions && !videoNoteMedia ? (
          <PostCommentActions onReply={onReply} onDelete={onDelete} />
        ) : null}
      </div>
    </article>
  );
}
