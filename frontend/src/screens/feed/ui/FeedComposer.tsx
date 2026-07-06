"use client";

import { AttachMenu } from "@/widgets/composer";
import { PostMediaBlock } from "@/entities/post";
import { onComposerShellMouseDown } from "@/shared/lib/composerPointerDown";
import type { FeedScreenState } from "@/screens/feed/model/useFeedScreen";
import { serializeRichTextEditor } from "@/shared/lib/telegram/richTextEditorDom";
import { EmojiPickerButton } from "@/shared/ui/EmojiPickerMenu";
import { RichTextEditor } from "@/shared/ui/RichTextEditor";

type Props = {
  ui: Pick<
    FeedScreenState["ui"],
    "composerReady" | "editorRef" | "draft" | "setDraft" | "pendingMedia"
  >;
  actions: Pick<
    FeedScreenState["actions"],
    "submitDraft" | "removePendingMedia" | "handleDraftKeyDown" | "handleAttach"
  >;
};

export function FeedComposer({ ui, actions }: Props) {
  const { composerReady, editorRef, draft, setDraft, pendingMedia } = ui;
  const { submitDraft, removePendingMedia, handleDraftKeyDown, handleAttach } = actions;

  return (
    <div
      className={`input-wrap${composerReady ? " is-composer-ready" : ""}`}
      onMouseDown={onComposerShellMouseDown}
    >
      <div className="composer-backdrop" aria-hidden="true" />
      <div className="input-box">
        {pendingMedia.length > 0 ? (
          <PostMediaBlock media={pendingMedia} onRemove={removePendingMedia} />
        ) : null}
        <RichTextEditor
          id="feed-input"
          editorRef={editorRef}
          value={draft}
          onChange={setDraft}
          onKeyDown={handleDraftKeyDown}
          placeholder="Написать пост..."
          className="feed-rich-text-input"
          ariaLabel="Текст поста"
        />
        <div className="input-bottom">
          <div className="input-tools">
            <AttachMenu scope="feed" onAttach={handleAttach} />
          </div>
          <div className="input-actions">
            <EmojiPickerButton
              editorRef={editorRef}
              onInserted={() => {
                const root = editorRef.current;
                if (!root) return;
                setDraft(serializeRichTextEditor(root));
              }}
            />
            <button className="send-btn" onClick={submitDraft} type="button">
              ↑
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
