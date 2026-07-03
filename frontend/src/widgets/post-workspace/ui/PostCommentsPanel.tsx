"use client";

import { useRef, useState } from "react";

import { useTelegramProfile } from "@/entities/channel";
import { postSupportsComments } from "@/entities/post/lib/postSupportsComments";
import { useAddPostComment, useDeletePostComment } from "@/entities/post";
import { PostMediaBlock } from "@/entities/post";
import { getApiErrorMessage } from "@/shared/api/getApiErrorMessage";
import { randomId } from "@/shared/lib/randomId";
import { showToast } from "@/shared/ui/toast";
import { PostReactionPills, PostViewsReposts } from "@/widgets/feed";
import type { Post, PostComment, PostMedia, PostMetrics } from "@/shared/types";

import CommentComposer from "./CommentComposer";
import PostCardCommentsSection from "./PostCardCommentsSection";

type Props = {
  post: Post;
  search: string;
  postCardRef: React.RefObject<HTMLDivElement | null>;
  badge: React.ReactNode;
  metrics: PostMetrics | null;
  media: PostMedia[];
  phoneFormat?: boolean;
};

export default function PostCommentsPanel({
  post,
  search,
  postCardRef,
  badge,
  metrics,
  media,
  phoneFormat = false,
}: Props) {
  const { addComment: savePostComment, isPending: isSavingComment } = useAddPostComment();
  const { deleteComment, deletingCommentIds } = useDeletePostComment();
  const { data: telegramProfile } = useTelegramProfile();
  const channelCommentsEnabled = telegramProfile?.commentsEnabled !== false;
  const showComments = postSupportsComments(post, channelCommentsEnabled);
  const canSyncComments = Boolean(post.telegramMessageId);
  const composerDisabled = canSyncComments && !showComments;
  const [replyTo, setReplyTo] = useState<PostComment | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const comments = post.comments ?? [];

  async function addComment(text: string, commentMedia: PostMedia[]) {
    const comment: PostComment = {
      id: randomId(),
      author: "Вы",
      date: new Date().toISOString(),
      text,
      ...(commentMedia.length > 0 ? { media: [...commentMedia] } : {}),
      ...(replyTo ? { replyToId: replyTo.id } : {}),
    };
    try {
      await savePostComment(post.id, comment);
      setReplyTo(null);
      requestAnimationFrame(() => {
        if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
      });
    } catch (error) {
      showToast({
        message: getApiErrorMessage(error, "Не удалось отправить комментарий"),
        variant: "error",
      });
      throw error;
    }
  }

  async function handleDeleteComment(comment: PostComment) {
    try {
      await deleteComment(post.id, comment.id);
    } catch (error) {
      showToast({
        message: getApiErrorMessage(error, "Не удалось удалить комментарий"),
        variant: "error",
      });
    }
  }

  return (
    <>
      <div className="composer-scroll-wrap">
        <div className="post-body post-comments-body" ref={scrollRef}>
          <div className="composer-scroll-body">
            <div className="post-body-inner">
              <div
                className={[
                  "post-msg-card",
                  phoneFormat ? "post-format-phone" : "",
                  "post-msg-card--readonly",
                  "post-msg-card--with-comments",
                  media.length === 0 &&
                  (post.status === "published" || post.status === "scheduled")
                    ? "post-card--no-media"
                    : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                ref={postCardRef}
              >
                <div className="post-card-body">
                  {media.length > 0 ? (
                    <div className="post-card-media">
                      <PostMediaBlock media={media} />
                    </div>
                  ) : null}
                  {post.text ? (
                    <div className="post-card-text">{post.text}</div>
                  ) : media.length === 0 ? (
                    <div className="post-card-text empty">Пост пустой</div>
                  ) : null}
                  {metrics ? <PostReactionPills reactions={metrics.reactions} /> : null}
                  <div className="post-card-footer">
                    <div className="post-meta">{badge}</div>
                    {metrics ? (
                      <PostViewsReposts views={metrics.views} reposts={metrics.reposts} />
                    ) : null}
                  </div>
                  <PostCardCommentsSection
                    comments={comments}
                    search={search}
                    postTelegramLinked={canSyncComments}
                    deletingCommentIds={deletingCommentIds}
                    onReply={(c) => setReplyTo(c)}
                    onDelete={handleDeleteComment}
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
      {composerDisabled ? (
        <p className="post-comments-disabled-hint">
          Включите обсуждения в настройках канала Telegram, чтобы писать комментарии с платформы.
        </p>
      ) : null}
      <CommentComposer
        replyTo={replyTo}
        onCancelReply={() => setReplyTo(null)}
        onSubmit={addComment}
        disabled={composerDisabled || isSavingComment}
      />
    </>
  );
}
