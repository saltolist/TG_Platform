"use client";

import { AttachMenuIconAttach, AttachMenuIconImage } from "./AttachMenuIcons";
import { AttachMediaGrid } from "./AttachMediaGrid";
import type { AttachedMediaItem } from "../lib/attachMenuUtils";
import type { AttachSubmenuKey } from "./AttachHomeScopeMenu";
import type { PostMedia } from "@/shared/types";

type Props = {
  submenu: AttachSubmenuKey;
  setSubmenu: (k: AttachSubmenuKey) => void;
  media: PostMedia[];
  postTitleText: string;
  attachedMedia: AttachedMediaItem[];
  hasAttachedPosts: boolean;
  onPickMedia: (media: PostMedia) => void;
  onPickAttachedMedia: (item: AttachedMediaItem) => void;
  onPickFile: () => void;
};

export default function AttachPostScopeMenu({
  submenu,
  setSubmenu,
  media,
  postTitleText,
  attachedMedia,
  hasAttachedPosts,
  onPickMedia,
  onPickAttachedMedia,
  onPickFile,
}: Props) {
  const hasMedia = media.length > 0;
  const hasAttachedMedia = attachedMedia.length > 0;
  return (
    <>
      {hasMedia ? (
        <div
          className={`ctx-item attach-parent${submenu === "postMedia" ? " active" : ""}`}
          onClick={(e) => {
            e.stopPropagation();
            setSubmenu(submenu === "postMedia" ? null : "postMedia");
          }}
        >
          <span className="attach-item-label">
            <AttachMenuIconImage />
            Медиа из поста
          </span>
          <span className="attach-chevron">›</span>
          {submenu === "postMedia" ? (
            <div
              className="ctx-dropdown attach-submenu attach-media-submenu open"
              onClick={(e) => e.stopPropagation()}
            >
              <AttachMediaGrid
                items={media.map((m) => ({
                  media: m,
                  title: `${postTitleText}: ${m.name}`,
                  onPick: () => onPickMedia(m),
                }))}
              />
            </div>
          ) : null}
        </div>
      ) : (
        <div className="ctx-item disabled">
          <span className="attach-item-label">
            <AttachMenuIconImage />
            В посте нет медиа
          </span>
        </div>
      )}
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
      <div className="ctx-item" onClick={onPickFile}>
        <span className="attach-item-label">
          <AttachMenuIconAttach />
          Загрузить с компьютера
        </span>
      </div>
    </>
  );
}
