"use client";

import { useRef, useState } from "react";

import { useAddPostComment } from "@/entities/post/model/usePostCommentMutations";
import { PostMediaBlock } from "@/entities/post";
import { randomId } from "@/shared/lib/randomId";
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
  const addPostComment = useAddPostComment();
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
    await addPostComment(post.id, comment);
    setReplyTo(null);
    requestAnimationFrame(() => {
      if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    });
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
                  ) : (
                    <div className="post-card-text empty">Пост пустой</div>
                  )}
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
                    onReply={(c) => setReplyTo(c)}
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
      <CommentComposer replyTo={replyTo} onCancelReply={() => setReplyTo(null)} onSubmit={addComment} />
    </>
  );
}
