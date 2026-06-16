"use client";

import { PostCommentsPanel, usePostWorkspace } from "@/widgets/post-workspace";
import { PostStatusBadge } from "@/entities/post";
import { EmptyState } from "@/shared/ui/empty-state";
import { PageHeader } from "@/widgets/page-header";
import PostChatView from "@/screens/post/ui/PostChatView";
import PostChatsView from "@/screens/post/ui/PostChatsView";
import PostNotesView from "@/screens/post/ui/PostNotesView";
import PostScreenHeader from "@/screens/post/ui/PostScreenHeader";

export function PostScreen() {
  const { isLoading, error, data, ui, actions } = usePostWorkspace();

  if (isLoading) {
    return (
      <div className="post-screen-wrap">
        <PageHeader className="page-header--post" title="Пост" onBack={actions.handleBack} />
        <EmptyState message="Загрузка поста…" className="min-h-[50vh]" />
      </div>
    );
  }

  if (error || !data.post) {
    return (
      <div className="post-screen-wrap">
        <PageHeader className="page-header--post" title="Пост" onBack={actions.handleBack} />
        <p className="post-not-found-msg">{error?.message ?? "Пост не найден"}</p>
      </div>
    );
  }

  const post = data.post;

  return (
    <div className={`post-screen-wrap${ui.layoutClassName}`} style={ui.layoutStyle}>
      <PostScreenHeader
        post={post}
        {...ui.postHeader}
        ctxItems={ui.ctxItems}
        ctxModal={ui.ctxModal}
        isMobile={ui.isMobile}
        onNavigateFeed={actions.navigateFeed}
        onOpenPostView={actions.openPostView}
        onResetToPostChatRoot={actions.resetToPostChatRoot}
        onGoToPostNotes={actions.goToPostNotes}
        onGoToPostChats={actions.goToPostChats}
        onBack={actions.handleBack}
      />
      <div className="post-layout" style={ui.layoutStyle}>
        {data.postMode === "chat" ? (
          <PostChatView post={post} data={data} ui={ui} actions={actions} />
        ) : data.postMode === "chats" ? (
          <PostChatsView post={post} ui={ui} actions={actions} />
        ) : data.postMode === "comments" ? (
          <PostCommentsPanel
            post={post}
            search={ui.listSearch}
            postCardRef={ui.postCardRef}
            badge={<PostStatusBadge post={post} />}
            metrics={post.status === "published" && post.metrics ? post.metrics : null}
            media={data.mediaItems}
            phoneFormat={ui.phoneFormat}
          />
        ) : (
          <PostNotesView post={post} ui={ui} actions={actions} />
        )}
      </div>
    </div>
  );
}
