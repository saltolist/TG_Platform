"use client";

import { AttachMenuIconAttach, AttachMenuIconImage } from "./AttachMenuIcons";
import { AttachMediaGrid } from "./AttachMediaGrid";
import type { AttachedMediaItem } from "../lib/attachMenuUtils";

export type AttachSubmenuKey = "pinnedMedia" | "postMedia" | null;

type Props = {
  submenu: AttachSubmenuKey;
  setSubmenu: (k: AttachSubmenuKey) => void;
  attachedMedia: AttachedMediaItem[];
  hasAttachedPosts: boolean;
  onPickAttachedMedia: (item: AttachedMediaItem) => void;
  onPickFile: () => void;
};

export default function AttachHomeScopeMenu({
  submenu,
  setSubmenu,
  attachedMedia,
  hasAttachedPosts,
  onPickAttachedMedia,
  onPickFile,
}: Props) {
  const hasAttachedMedia = attachedMedia.length > 0;
  return (
    <>
      <div className="ctx-item" onClick={onPickFile}>
        <span className="attach-item-label">
          <AttachMenuIconAttach />
          Прикрепить файл
        </span>
      </div>

      {hasAttachedPosts ? (
        <div
          className={`ctx-item attach-parent${submenu === "pinnedMedia" ? " active" : ""}`}
          onClick={(e) => {
            e.stopPropagation();
            setSubmenu(submenu === "pinnedMedia" ? null : "pinnedMedia");
          }}
        >
          <span className="attach-item-label">
            <AttachMenuIconImage />
            Медиа из прикреплённых постов
          </span>
          <span className="attach-chevron">›</span>
          {submenu === "pinnedMedia" ? (
            <div
              className="ctx-dropdown attach-submenu attach-media-submenu open"
              onClick={(e) => e.stopPropagation()}
            >
              {hasAttachedMedia ? (
                <AttachMediaGrid
                  items={attachedMedia.map((item) => ({
                    media: item.media,
                    title: `${item.postTitle}: ${item.media.name}`,
                    onPick: () => onPickAttachedMedia(item),
                  }))}
                />
              ) : (
                <div className="ctx-item disabled">У прикреплённых постов нет медиа</div>
              )}
            </div>
          ) : null}
        </div>
      ) : null}
    </>
  );
}
