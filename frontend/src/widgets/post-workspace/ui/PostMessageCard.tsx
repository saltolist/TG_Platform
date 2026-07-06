"use client";

import { useEffect, useRef, useState, type RefObject } from "react";

import { PostMediaBlock } from "@/entities/post";
import { PostTelegramSyncLabel } from "@/entities/post/ui/PostTelegramSyncLabel";
import { readFileAsMedia } from "@/shared/lib/helpers";
import { ensureVisibleInScrollParent } from "@/shared/lib/scrollIntoParent";
import type { PostTextContent } from "@/shared/lib/telegram/richTextEditorDom";
import { serializeRichTextEditor } from "@/shared/lib/telegram/richTextEditorDom";
import { NoteIconAttach } from "@/shared/ui/icons/note-header-icons";
import { PostReactionPills, PostViewsReposts } from "@/widgets/feed";
import type { PostComment, PostMedia, PostMetrics } from "@/shared/types";
import { TelegramFormattedText } from "@/shared/ui/TelegramFormattedText";
import { RichTextEditor } from "@/shared/ui/RichTextEditor";

import PostCardToolbar from "./PostCardToolbar";
import PostCommentsRow from "./PostCommentsRow";

type Props = {
  cardRef: RefObject<HTMLDivElement | null>;
  isEditing: boolean;
  isSaving?: boolean;
  text: string;
  textHtml?: string;
  media: PostMedia[];
  isTextOnlyNoMedia?: boolean;
  onStartEdit: () => void;
  onCancel: () => void;
  onSave: (content: PostTextContent, media: PostMedia[]) => void;
  badge: React.ReactNode;
  metrics: PostMetrics | null;
  comments?: PostComment[];
  onOpenComments?: () => void;
  commentsEnabled?: boolean;
  phoneFormat?: boolean;
  /** Copy/edit toolbar and inline editing (off for TG sticker / video-note posts). */
  contentEditable?: boolean;
};

export default function PostMessageCard({
  cardRef,
  isEditing,
  isSaving = false,
  text,
  textHtml,
  media,
  onStartEdit,
  onCancel,
  onSave,
  badge,
  metrics,
  comments,
  onOpenComments,
  commentsEnabled = true,
  isTextOnlyNoMedia,
  phoneFormat,
  contentEditable = true,
}: Props) {
  const showComments = !!metrics && commentsEnabled;
  const [draft, setDraft] = useState<PostTextContent>({ text, textHtml });
  const [mediaDraft, setMediaDraft] = useState<PostMedia[]>(media);
  const editorRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const wasEditingRef = useRef(false);

  useEffect(() => {
    const enteredEdit = isEditing && !wasEditingRef.current;
    wasEditingRef.current = isEditing;

    if (enteredEdit) {
      setDraft({ text, textHtml });
      setMediaDraft(media);
      return;
    }
    if (!isEditing && !isSaving) {
      setDraft({ text, textHtml });
      setMediaDraft(media);
    }
  }, [text, textHtml, media, isEditing, isSaving]);

  useEffect(() => {
    if (!isEditing || isSaving) return;
    const id = window.setTimeout(() => {
      const editor = editorRef.current;
      if (editor) {
        editor.focus({ preventScroll: true });
        const selection = window.getSelection();
        const range = document.createRange();
        range.selectNodeContents(editor);
        range.collapse(false);
        selection?.removeAllRanges();
        selection?.addRange(range);
      }
      const block = cardRef.current?.closest<HTMLElement>(".post-msg-block");
      const scrollParent = document.getElementById("post-chat-scroll");
      if (block && scrollParent) {
        ensureVisibleInScrollParent(block, scrollParent);
      }
    }, 30);
    return () => window.clearTimeout(id);
  }, [isEditing, isSaving, cardRef]);

  async function onPickFile(e: React.ChangeEvent<HTMLInputElement>) {
    if (isSaving) return;
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
  const editorLocked = isSaving;
  const canEditContent = contentEditable && !editorLocked;

  function handleSave() {
    const content: PostTextContent = editorRef.current
      ? serializeRichTextEditor(editorRef.current)
      : draft;
    onSave(content, mediaDraft);
  }

  return (
    <div
      className={`post-msg-block${phoneFormat ? " post-format-phone" : ""}${editorLocked ? " post-msg-block--saving" : ""}`}
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
                  onRemove={
                    editorLocked
                      ? undefined
                      : (i) => setMediaDraft((arr) => arr.filter((_, j) => j !== i))
                  }
                />
              </div>
            ) : null
          ) : media.length > 0 ? (
            <div className="post-card-media">
              <PostMediaBlock media={media} />
            </div>
          ) : null}
          {isEditing ? (
            <RichTextEditor
              editorRef={editorRef}
              value={draft}
              onChange={setDraft}
              placeholder="Пост пустой — начни писать..."
              className={[
                "post-card-text",
                "post-msg-textarea",
                !draft.text.trim() && mediaDraft.length === 0 ? "empty" : "",
                editorLocked ? "post-msg-textarea--locked" : "",
              ]
                .filter(Boolean)
                .join(" ")}
              ariaLabel="Текст поста"
              disabled={editorLocked}
            />
          ) : text || textHtml ? (
            <TelegramFormattedText text={text} textHtml={textHtml} className="post-card-text" />
          ) : media.length === 0 ? (
            <div className="post-card-text empty">Пост пустой — начни писать...</div>
          ) : null}
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
            disabled={editorLocked}
          />
          <div className={`post-edit-toolbar${editorLocked ? " post-edit-toolbar--syncing" : ""}`}>
            {editorLocked ? (
              <PostTelegramSyncLabel className="post-edit-sync-label" />
            ) : (
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
                  onClick={handleSave}
                  type="button"
                >
                  Сохранить
                </button>
                <button className="btn btn-ghost post-edit-btn" onClick={onCancel} type="button">
                  Отмена
                </button>
              </div>
            )}
          </div>
        </div>
      ) : canEditContent ? (
        <PostCardToolbar plainText={copyText} onEdit={onStartEdit} />
      ) : null}
    </div>
  );
}
