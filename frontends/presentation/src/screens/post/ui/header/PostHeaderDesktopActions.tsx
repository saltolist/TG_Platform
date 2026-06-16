"use client";

import { BackButton } from "@/shared/ui/back-button";
import { ContextMenu, type CtxMenuItem } from "@/shared/ui/context-menu";
import type { PostMode } from "@/shared/types";

type Props = {
  postMode: PostMode;
  showJump: boolean;
  showPostModeButtons: boolean;
  ctxItems: CtxMenuItem[];
  onScrollToPost: () => void;
  onGoToPostNotes: () => void;
  onGoToPostChats: () => void;
  onBack: () => void;
};

export default function PostHeaderDesktopActions({
  postMode,
  showJump,
  showPostModeButtons,
  ctxItems,
  onScrollToPost,
  onGoToPostNotes,
  onGoToPostChats,
  onBack,
}: Props) {
  return (
    <>
      <button
        type="button"
        className={`jump-post-btn${showJump ? " visible" : ""}`}
        onClick={onScrollToPost}
      >
        ↑ К посту
      </button>
      {showPostModeButtons ? (
        <>
          <div className="post-mode-cluster">
            <button
              className={`btn btn-ghost btn-sm post-mode-btn${postMode === "notes" ? " active" : ""}`}
              onClick={onGoToPostNotes}
              type="button"
            >
              Заметки
            </button>
          </div>
          <div className="post-mode-cluster">
            <button
              className={`btn btn-ghost btn-sm post-mode-btn${postMode === "chats" ? " active" : ""}`}
              onClick={onGoToPostChats}
              type="button"
            >
              Чаты
            </button>
          </div>
        </>
      ) : null}
      <BackButton onClick={onBack} className="post-back-btn" />
      {showPostModeButtons ? (
        <ContextMenu
          items={ctxItems}
          portal
          align="right"
          dropdownClassName="ctx-dropdown--page-header-control"
        />
      ) : null}
    </>
  );
}
