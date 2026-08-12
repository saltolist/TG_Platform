"use client";

import { BackButton } from "@/shared/ui/back-button";
import { ContextMenu, type CtxMenuItem } from "@/shared/ui/context-menu";
import type { PostMode } from "@/shared/types";
import type { PageHeaderOverflowItem } from "@/widgets/page-header";

type Props = {
  postMode: PostMode;
  showJump: boolean;
  showPostModeButtons: boolean;
  overflowItems: PageHeaderOverflowItem[];
  onScrollToPost: () => void;
  onGoToPostNotes: () => void;
  onGoToPostChats: () => void;
  onBack: () => void;
};

export default function PostHeaderDesktopActions({
  postMode,
  showJump,
  showPostModeButtons,
  overflowItems,
  onScrollToPost,
  onGoToPostNotes,
  onGoToPostChats,
  onBack,
}: Props) {
  const menuItems: CtxMenuItem[] = overflowItems
    .filter((item) => !item.hidden)
    .map((item) => ({
      label: item.label,
      icon: item.icon,
      danger: item.danger,
      disabled: item.disabled,
      active: item.active,
      onClick: item.onClick,
    }));

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
      <BackButton onClick={onBack} />
      {showPostModeButtons ? (
        <ContextMenu
          items={menuItems}
          portal
          align="right"
          dropdownClassName="ctx-dropdown--page-header-control"
        />
      ) : null}
    </>
  );
}
