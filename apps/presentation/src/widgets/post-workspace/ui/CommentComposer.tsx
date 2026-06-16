"use client";

import { useEffect, useRef, useState } from "react";

import { PostMediaBlock } from "@/entities/post";
import { onComposerShellMouseDown } from "@/shared/lib/composerPointerDown";
import { autoResize, readFileAsMedia } from "@/shared/lib/helpers";
import type { PostComment, PostMedia } from "@/shared/types";
import { AttachMenu } from "@/widgets/composer";

function replyPreviewText(comment: PostComment): string {
  const text = comment.text.trim();
  if (text) return text;
  if (comment.media?.length) return "Медиа";
  return "Комментарий";
}

type Props = {
  replyTo: PostComment | null;
  onCancelReply: () => void;
  onSubmit: (text: string, media: PostMedia[]) => void;
};

export default function CommentComposer({ replyTo, onCancelReply, onSubmit }: Props) {
  const [draft, setDraft] = useState("");
  const [pendingMedia, setPendingMedia] = useState<PostMedia[]>([]);
  const taRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (taRef.current) autoResize(taRef.current, 16);
  }, [draft]);

  useEffect(() => {
    if (replyTo) taRef.current?.focus();
  }, [replyTo]);

  function removePendingMedia(index: number) {
    setPendingMedia((arr) => arr.filter((_, i) => i !== index));
  }

  function submit() {
    const text = draft.trim();
    if (!text && pendingMedia.length === 0) return;
    onSubmit(text, pendingMedia);
    setDraft("");
    setPendingMedia([]);
  }

  return (
    <div className="input-wrap post-comments-input-wrap" onMouseDown={onComposerShellMouseDown}>
      <div className="composer-backdrop" aria-hidden="true" />
      <div className={`input-box${replyTo ? " input-box--replying" : ""}`}>
        {replyTo ? (
          <div className="comment-composer-reply">
            <div className="comment-composer-reply-line">
              <span className="comment-composer-reply-author">{replyTo.author}</span>
              <span className="comment-composer-reply-text">{replyPreviewText(replyTo)}</span>
            </div>
            <button
              className="comment-composer-reply-cancel"
              onClick={onCancelReply}
              type="button"
              aria-label="Отменить ответ"
            >
              ✕
            </button>
          </div>
        ) : null}
        {pendingMedia.length > 0 ? (
          <PostMediaBlock media={pendingMedia} onRemove={removePendingMedia} />
        ) : null}
        <textarea
          ref={taRef}
          placeholder="Написать комментарий..."
          rows={1}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
            if (e.key === "Escape" && replyTo) {
              e.preventDefault();
              onCancelReply();
            }
            if (e.key === "Backspace" && draft === "" && pendingMedia.length > 0) {
              e.preventDefault();
              setPendingMedia((arr) => arr.slice(0, -1));
            }
          }}
        />
        <div className="input-bottom">
          <div className="input-tools">
            <AttachMenu
              scope="feed"
              onAttach={async (att) => {
                if (att.kind === "file" && att.file) {
                  try {
                    const media = await readFileAsMedia(att.file);
                    setPendingMedia((arr) => [...arr, media]);
                  } catch {
                    /* ignore read errors (clipboard, permissions) */
                  }
                }
              }}
            />
          </div>
          <button className="send-btn" onClick={submit} type="button" aria-label="Отправить комментарий">
            ↑
          </button>
        </div>
      </div>
    </div>
  );
}
