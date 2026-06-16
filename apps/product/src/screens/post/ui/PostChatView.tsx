"use client";

import { Composer } from "@/widgets/composer";
import { ChatMessage } from "@/widgets/chat-thread";
import { PostMessageCard, type PostWorkspace } from "@/widgets/post-workspace";
import { PostStatusBadge } from "@/entities/post";
import type { Post } from "@/shared/types";

type Props = {
  post: Post;
  data: Pick<
    PostWorkspace["data"],
    | "isEditing"
    | "mediaItems"
    | "flatMessages"
    | "lastAssistantFlat"
    | "activeChat"
  >;
  ui: Pick<PostWorkspace["ui"], "phoneFormat" | "chatScrollRef" | "postCardRef">;
  actions: Pick<
    PostWorkspace["actions"],
    "startEdit" | "cancelEdit" | "savePost" | "openComments" | "sendPost"
  >;
};

export default function PostChatView({ post, data, ui, actions }: Props) {
  const { isEditing, mediaItems, flatMessages, lastAssistantFlat, activeChat } = data;
  const { phoneFormat, chatScrollRef, postCardRef } = ui;
  const { startEdit, cancelEdit, savePost, openComments, sendPost } = actions;

  return (
    <>
      <div className="composer-scroll-wrap">
        <div className="post-body" id="post-chat-scroll" ref={chatScrollRef}>
          <div className="composer-scroll-body">
            <div className="post-body-inner">
              <PostMessageCard
                cardRef={postCardRef}
                isEditing={isEditing}
                text={post.text}
                media={mediaItems}
                onStartEdit={startEdit}
                onCancel={cancelEdit}
                onSave={savePost}
                badge={<PostStatusBadge post={post} />}
                metrics={post.status === "published" && post.metrics ? post.metrics : null}
                comments={post.status === "published" ? (post.comments ?? []) : undefined}
                onOpenComments={openComments}
                isTextOnlyNoMedia={
                  mediaItems.length === 0 &&
                  (post.status === "published" ||
                    post.status === "scheduled" ||
                    post.status === "draft")
                }
                phoneFormat={phoneFormat}
              />
              {flatMessages.map(({ message: m, path }, i) => (
                <ChatMessage
                  key={path.join("-")}
                  message={m}
                  ctx={{
                    scope: "post",
                    postId: post.id,
                    entityId: activeChat?.id ?? "",
                    path,
                  }}
                  isLastAssistantMessage={m.role === "ai" && i === lastAssistantFlat}
                />
              ))}
            </div>
          </div>
        </div>
      </div>
      <Composer scope="post" onSubmit={sendPost} />
    </>
  );
}
