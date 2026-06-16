"use client";

import { PostMediaBlock } from "@/entities/post";
import { formatStoredDate } from "@/shared/lib/helpers";
import { avatarHue, avatarInitials } from "@/shared/lib/postComments";
import type { PostComment } from "@/shared/types";

type Props = {
  comment: PostComment;
  parent?: PostComment;
  onReply?: () => void;
};

export default function PostCommentRow({ comment, parent, onReply }: Props) {
  const hue = avatarHue(comment.author);
  return (
    <article className={`post-comment${parent ? " post-comment--reply" : ""}`}>
      <div
        className="post-comment-avatar"
        style={{ background: `hsl(${hue} 42% 38%)` }}
        aria-hidden
      >
        {avatarInitials(comment.author)}
      </div>
      <div className="post-comment-main">
        <div className="post-comment-head">
          <span className="post-comment-author">{comment.author}</span>
          <span className="post-comment-date">{formatStoredDate(comment.date)}</span>
        </div>
        {parent ? (
          <div className="post-comment-quote">
            <span className="post-comment-quote-author">{parent.author}</span>
            <span className="post-comment-quote-text">{parent.text}</span>
          </div>
        ) : null}
        {comment.media && comment.media.length > 0 ? (
          <div className="post-comment-media">
            <PostMediaBlock media={comment.media} />
          </div>
        ) : null}
        {comment.text ? <p className="post-comment-text">{comment.text}</p> : null}
        {onReply ? (
          <button className="post-comment-reply-btn" onClick={onReply} type="button">
            Ответить
          </button>
        ) : null}
      </div>
    </article>
  );
}
