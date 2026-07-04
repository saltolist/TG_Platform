"use client";

import { PostMediaBlock } from "@/entities/post";
import { PostTelegramSyncLabel } from "@/entities/post/ui/PostTelegramSyncLabel";
import { formatStoredDate, isStickerKind, isVideoMedia, isVideoNoteKind } from "@/shared/lib/helpers";
import { avatarHue, avatarInitials } from "@/shared/lib/postComments";
import type { PostComment } from "@/shared/types";
import { TelegramFormattedText } from "@/shared/ui/TelegramFormattedText";

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
  const singleMedia = comment.media?.length === 1 ? comment.media[0] : null;
  const videoNoteMedia =
    singleMedia != null &&
    !isStickerKind(singleMedia) &&
    (isVideoNoteKind(singleMedia) || (isVideoMedia(singleMedia) && singleMedia.kind == null));
  const stickerMedia = singleMedia != null && isStickerKind(singleMedia);
  const compactMedia = videoNoteMedia || stickerMedia;
  const showPendingTelegram = isDeleting || telegramSyncing;
  const showActions = Boolean(onReply || onDelete) && !showPendingTelegram;

  return (
    <article
      className={[
        "post-comment",
        parent ? "post-comment--reply" : "",
        isDeleting ? "post-comment--pending" : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <div
        className="post-comment-avatar"
        style={{ background: `hsl(${hue} 42% 38%)` }}
        aria-hidden
      >
        {avatarInitials(comment.author)}
      </div>
      <div className="post-comment-main">
        <div className="post-comment-head">
          {showPendingTelegram ? (
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
          compactMedia ? (
            <div className="post-comment-compact">
              <div
                className={`post-comment-media${videoNoteMedia ? " post-comment-media--video-note" : ""}`}
              >
                <PostMediaBlock media={comment.media} variant="comment" />
              </div>
              {showActions ? (
                <PostCommentActions
                  className={videoNoteMedia ? "post-comment-actions--video-note" : undefined}
                  onReply={onReply}
                  onDelete={onDelete}
                />
              ) : null}
            </div>
          ) : (
            <div className="post-comment-media">
              <PostMediaBlock media={comment.media} variant="comment" />
            </div>
          )
        ) : null}
        {(comment.text || comment.textHtml) ? (
          <TelegramFormattedText
            text={comment.text}
            textHtml={comment.textHtml}
            className="post-comment-text"
          />
        ) : null}
        {showActions && !compactMedia ? (
          <PostCommentActions onReply={onReply} onDelete={onDelete} />
        ) : null}
      </div>
    </article>
  );
}
