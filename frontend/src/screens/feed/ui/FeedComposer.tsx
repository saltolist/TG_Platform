"use client";

import { AttachMenu } from "@/widgets/composer";
import { PostMediaBlock } from "@/entities/post";
import { onComposerShellMouseDown } from "@/shared/lib/composerPointerDown";
import type { FeedScreenState } from "@/screens/feed/model/useFeedScreen";

type Props = {
  ui: Pick<
    FeedScreenState["ui"],
    "composerReady" | "taRef" | "draft" | "setDraft" | "pendingMedia"
  >;
  actions: Pick<
    FeedScreenState["actions"],
    "submitDraft" | "removePendingMedia" | "handleDraftKeyDown" | "handleAttach"
  >;
};

export function FeedComposer({ ui, actions }: Props) {
  const { composerReady, taRef, draft, setDraft, pendingMedia } = ui;
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
        <textarea
          ref={taRef}
          id="feed-input"
          placeholder="Написать пост..."
          rows={1}
          autoComplete="off"
          suppressHydrationWarning
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={handleDraftKeyDown}
        />
        <div className="input-bottom">
          <div className="input-tools">
            <AttachMenu scope="feed" onAttach={handleAttach} />
          </div>
          <button className="send-btn" onClick={submitDraft} type="button">
            ↑
          </button>
        </div>
      </div>
    </div>
  );
}
