"use client";

import PostHeaderDesktopActions from "@/screens/post/ui/header/PostHeaderDesktopActions";
import { buildPostBreadcrumbTrail } from "@/shared/lib/nav/breadcrumbTrails";
import { Breadcrumb } from "@/shared/ui/breadcrumb";
import { PageHeader, PageHeaderSearchInput } from "@/widgets/page-header";
import type { PostScreenHeaderState } from "@/widgets/post-workspace";
import type { CtxMenuItem } from "@/shared/ui/context-menu";
import type { Post } from "@/shared/types";
import type { ReactNode } from "react";

type Props = PostScreenHeaderState & {
  post: Post;
  ctxItems: CtxMenuItem[];
  ctxModal: ReactNode;
  isMobile: boolean;
  onNavigateFeed: () => void;
  onOpenPostView: () => void;
  onResetToPostChatRoot: () => void;
  onGoToPostNotes: () => void;
  onGoToPostChats: () => void;
  onBack: () => void;
};

export default function PostScreenHeader({
  post,
  ctxItems,
  ctxModal,
  isMobile,
  postSubPage,
  showListHeaderSearch,
  listSearchPlaceholder,
  postIntermediateCrumb,
  showJump,
  showPostModeButtons,
  showPostTabletOverflow,
  postHeaderOverflowItems,
  scrollToPost,
  listSearch,
  setListSearch,
  postMode,
  currentPostChatId,
  activeChat,
  onNavigateFeed,
  onOpenPostView,
  onResetToPostChatRoot,
  onGoToPostNotes,
  onGoToPostChats,
  onBack,
}: Props) {
  const headerClassName = [
    "page-header--post",
    showListHeaderSearch && "page-header--post-with-search",
    showJump && "page-header--post-has-jump",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <>
      <PageHeader
        className={headerClassName}
        showBack={false}
        left={
          <Breadcrumb
            items={buildPostBreadcrumbTrail({
              post,
              postMode,
              currentPostChatId,
              activeChat,
              postSubPage,
              postIntermediateCrumb,
              onNavigateFeed,
              onOpenPostView,
              onResetToPostChatRoot,
            })}
          />
        }
        search={
          showListHeaderSearch ? (
            <div className="post-header-search-row">
              <PageHeaderSearchInput
                placeholder={listSearchPlaceholder}
                value={listSearch}
                onChange={(e) => setListSearch(e.target.value)}
                onDismiss={() => setListSearch("")}
              />
            </div>
          ) : undefined
        }
        compactSearchOverlay={showListHeaderSearch}
        actions={
          !isMobile ? (
            <PostHeaderDesktopActions
              postMode={postMode}
              showJump={showJump}
              showPostModeButtons={showPostModeButtons}
              ctxItems={ctxItems}
              onScrollToPost={scrollToPost}
              onGoToPostNotes={onGoToPostNotes}
              onGoToPostChats={onGoToPostChats}
              onBack={onBack}
            />
          ) : undefined
        }
        overflowItems={
          isMobile || showPostTabletOverflow ? postHeaderOverflowItems : undefined
        }
      />
      {ctxModal}
    </>
  );
}
