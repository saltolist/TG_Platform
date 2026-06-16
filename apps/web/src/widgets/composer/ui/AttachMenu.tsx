"use client";

import { createPortal } from "react-dom";
import { useAttachMenu } from "@/widgets/composer/model/useAttachMenu";
import { postTitle } from "@/shared/lib/helpers";
import type { ComposerAttachment } from "@/shared/types";
import AttachHomeScopeMenu from "./AttachHomeScopeMenu";
import AttachPostScopeMenu from "./AttachPostScopeMenu";
import type { AttachScope } from "@/widgets/composer/model/useAttachMenu";

export type { AttachScope };

type Props = {
  scope: AttachScope;
  onAttach: (att: ComposerAttachment) => void;
  placement?: "up" | "down";
  attachments?: ComposerAttachment[];
};

export default function AttachMenu(props: Props) {
  const {
    scope,
    open,
    pos,
    submenu,
    setSubmenu,
    wrapRef,
    btnRef,
    dropdownRef,
    fileInputRef,
    onTriggerClick,
    onFilePicked,
    pickFile,
    currentPost,
    postMedia,
    attachedPostIds,
    attachedPostsMedia,
    attachMediaFromPost,
    attachMediaFromPinned,
  } = useAttachMenu(props);

  const dropdownContent =
    open && scope !== "feed" && pos ? (
      <div
        ref={dropdownRef}
        className={`ctx-dropdown attach-dropdown open attach-dropdown-${pos.mode}`}
        style={
          pos.mode === "down"
            ? { top: pos.top, left: pos.left }
            : { bottom: pos.bottom, left: pos.left }
        }
      >
        {scope === "post" ? (
          <AttachPostScopeMenu
            submenu={submenu}
            setSubmenu={setSubmenu}
            media={postMedia}
            postTitleText={currentPost ? postTitle(currentPost) : ""}
            attachedMedia={attachedPostsMedia}
            hasAttachedPosts={attachedPostIds.length > 0}
            onPickMedia={(media) => attachMediaFromPost(media.name)}
            onPickAttachedMedia={attachMediaFromPinned}
            onPickFile={pickFile}
          />
        ) : (
          <AttachHomeScopeMenu
            submenu={submenu}
            setSubmenu={setSubmenu}
            attachedMedia={attachedPostsMedia}
            hasAttachedPosts={attachedPostIds.length > 0}
            onPickAttachedMedia={attachMediaFromPinned}
            onPickFile={pickFile}
          />
        )}
      </div>
    ) : null;

  return (
    <div className="ctx-wrap attach-wrap" ref={wrapRef}>
      <button
        ref={btnRef}
        className="icon-btn attach-btn"
        title="Добавить"
        type="button"
        onClick={onTriggerClick}
        aria-label="Добавить"
      >
        <svg
          className="attach-btn-icon"
          viewBox="0 0 24 24"
          aria-hidden="true"
          fill="none"
          stroke="currentColor"
          strokeWidth={2.5}
          strokeLinecap="round"
        >
          <line x1="12" y1="5" x2="12" y2="19" />
          <line x1="5" y1="12" x2="19" y2="12" />
        </svg>
      </button>
      <input type="file" ref={fileInputRef} style={{ display: "none" }} onChange={onFilePicked} />
      {dropdownContent && typeof document !== "undefined"
        ? createPortal(dropdownContent, document.body)
        : null}
    </div>
  );
}
