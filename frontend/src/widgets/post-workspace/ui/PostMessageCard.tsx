"use client";

import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";

import { PostMediaBlock } from "@/entities/post";
import { readFileAsMedia } from "@/shared/lib/helpers";
import { ensureVisibleInScrollParent } from "@/shared/lib/scrollIntoParent";
import { NoteIconAttach } from "@/shared/ui/icons/note-header-icons";
import { PostReactionPills, PostViewsReposts } from "@/widgets/feed";
import type { PostComment, PostMedia, PostMetrics } from "@/shared/types";

import PostCardToolbar from "./PostCardToolbar";
import PostCommentsRow from "./PostCommentsRow";

type Props = {
  cardRef: RefObject<HTMLDivElement | null>;
  isEditing: boolean;
  text: string;
  media: PostMedia[];
  isTextOnlyNoMedia?: boolean;
  onStartEdit: () => void;
  onCancel: () => void;
  onSave: (text: string, media: PostMedia[]) => void;
  badge: React.ReactNode;
  metrics: PostMetrics | null;
  comments?: PostComment[];
  onOpenComments?: () => void;
  phoneFormat?: boolean;
};

export default function PostMessageCard({
  cardRef,
  isEditing,
  text,
  media,
  onStartEdit,
  onCancel,
  onSave,
  badge,
  metrics,
  comments,
  onOpenComments,
  isTextOnlyNoMedia,
  phoneFormat,
}: Props) {
  const showComments = !!metrics;
  const [draft, setDraft] = useState(text);
  const [mediaDraft, setMediaDraft] = useState<PostMedia[]>(media);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setDraft(text);
    setMediaDraft(media);
  }, [text, media, isEditing]);

  useEffect(() => {
    if (!isEditing) return;
    const id = window.setTimeout(() => {
      const ta = taRef.current;
      if (ta) {
        ta.focus({ preventScroll: true });
        ta.setSelectionRange(ta.value.length, ta.value.length);
      }
      const block = cardRef.current?.closest<HTMLElement>(".post-msg-block");
      const scrollParent = document.getElementById("post-chat-scroll");
      if (block && scrollParent) {
        ensureVisibleInScrollParent(block, scrollParent);
      }
    }, 30);
    return () => window.clearTimeout(id);
  }, [isEditing, cardRef]);

  useLayoutEffect(() => {
    if (!isEditing) return;
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = ta.scrollHeight + "px";
  }, [isEditing, draft]);

  async function onPickFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) {
      try {
        const m = await readFileAsMedia(file);
        setMediaDraft((arr) => [...arr, m]);
      } catch {
        /* ignore read errors */
      }
    }
    e.target.value = "";
  }

  const copyText = text.trim() || "";

  return (
    <div
      className={`post-msg-block${phoneFormat ? " post-format-phone" : ""}`}
      id="post-msg-card"
    >
      <div
        ref={cardRef}
        className={[
          "post-card",
          "post-msg-card",
          showComments ? "post-msg-card--with-comments" : "",
          isTextOnlyNoMedia ? "post-card--no-media" : "",
        ]
          .filter(Boolean)
          .join(" ")}
      >
        <div className="post-card-body">
          {isEditing ? (
            mediaDraft.length > 0 ? (
              <div className="post-msg-media-edit">
                <PostMediaBlock
                  media={mediaDraft}
                  onRemove={(i) => setMediaDraft((arr) => arr.filter((_, j) => j !== i))}
                />
              </div>
            ) : null
          ) : media.length > 0 ? (
            <div className="post-card-media">
              <PostMediaBlock media={media} />
            </div>
          ) : null}
          {isEditing ? (
            <textarea
              ref={taRef}
              className={[
                "post-card-text",
                "post-msg-textarea",
                !draft.trim() ? "empty" : "",
              ]
                .filter(Boolean)
                .join(" ")}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Пост пустой — начни писать..."
              rows={1}
              spellCheck={false}
              aria-label="Текст поста"
            />
          ) : text ? (
            <div className="post-card-text">{text}</div>
          ) : (
            <div className="post-card-text empty">Пост пустой — начни писать...</div>
          )}
          {metrics ? <PostReactionPills reactions={metrics.reactions} /> : null}
          <div className="post-card-footer">
            <div className="post-meta">{badge}</div>
            {metrics ? (
              <PostViewsReposts views={metrics.views} reposts={metrics.reposts} />
            ) : null}
          </div>
          {showComments ? (
            <PostCommentsRow
              count={comments?.length ?? 0}
              onClick={
                !isEditing && onOpenComments
                  ? (e) => {
                      e.stopPropagation();
                      onOpenComments();
                    }
                  : undefined
              }
            />
          ) : null}
        </div>
      </div>
      {isEditing ? (
        <div className="post-msg-actions" aria-label="Редактирование поста">
          <input
            type="file"
            ref={fileRef}
            style={{ display: "none" }}
            accept="image/*,video/*"
            onChange={onPickFile}
          />
          <div className="post-edit-toolbar">
            <div className="msg-user-edit-bar">
              <button
                className="note-header-plain-btn note-header-plain-btn--sm note-header-plain-btn--attach"
                onClick={() => fileRef.current?.click()}
                type="button"
                title="Прикрепить файл"
                aria-label="Прикрепить файл"
              >
                <NoteIconAttach />
              </button>
              <button
                className="btn btn-primary post-edit-btn"
                onClick={() => onSave(draft, mediaDraft)}
                type="button"
              >
                Сохранить
              </button>
              <button className="btn btn-ghost post-edit-btn" onClick={onCancel} type="button">
                Отмена
              </button>
            </div>
          </div>
        </div>
      ) : (
        <PostCardToolbar plainText={copyText} onEdit={onStartEdit} />
      )}
    </div>
  );
}
