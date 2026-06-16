"use client";

import { createPortal } from "react-dom";
import { useComposerEditor } from "@/widgets/composer/model/useComposerEditor";
import { onComposerShellMouseDown } from "@/shared/lib/composerPointerDown";
import type { ComposerScope } from "@/shared/types";
import ComposerMentionDropdown from "./ComposerMentionDropdown";
import ComposerToolbar from "./ComposerToolbar";

type Props = {
  scope: ComposerScope;
  placeholder?: string;
  onSubmit: (text: string) => boolean;
};

export default function Composer({ scope, placeholder, onSubmit }: Props) {
  const {
    placement,
    editorRef,
    inputBoxRef,
    mentionRef,
    isEmpty,
    effectivePlaceholder,
    maxLines,
    attachments,
    mentionMatches,
    mentionIndex,
    mentionPos,
    mentionOpen,
    llmOptions,
    webOptions,
    llmId,
    webId,
    isMulti,
    setComposerLlm,
    setComposerWeb,
    setMentionIndex,
    addAttachmentInline,
    pickMention,
    onEditorInput,
    onKeyDown,
    onPaste,
    normalizeEmptyEditorFocus,
    refreshMention,
    submit,
  } = useComposerEditor({ scope, placeholder, onSubmit });

  const mentionDropdown =
    mentionOpen && mentionPos ? (
      <ComposerMentionDropdown
        mentionRef={mentionRef}
        mentionPos={mentionPos}
        matches={mentionMatches}
        activeIndex={mentionIndex}
        onHoverIndex={setMentionIndex}
        onPick={pickMention}
      />
    ) : null;

  return (
    <div className="input-wrap" onMouseDown={onComposerShellMouseDown}>
      <div className="composer-backdrop" aria-hidden="true" />
      <div
        className="input-box"
        ref={inputBoxRef}
        style={{ ["--composer-max-lines" as string]: String(maxLines) }}
      >
        <div className="composer-field">
          <div
            ref={editorRef}
            className={`composer-editor${isEmpty ? " is-empty" : ""}`}
            contentEditable
            suppressContentEditableWarning
            role="textbox"
            aria-multiline="true"
            aria-label={effectivePlaceholder}
            data-placeholder={effectivePlaceholder}
            onInput={onEditorInput}
            onFocus={normalizeEmptyEditorFocus}
            onKeyDown={onKeyDown}
            onKeyUp={refreshMention}
            onClick={() => {
              normalizeEmptyEditorFocus();
              refreshMention();
            }}
            onPaste={onPaste}
          />
        </div>
        <ComposerToolbar
          scope={scope}
          placement={placement}
          attachments={attachments}
          onAttach={addAttachmentInline}
          isMulti={isMulti}
          llmOptions={llmOptions}
          webOptions={webOptions}
          llmId={llmId}
          webId={webId}
          onLlmChange={(id) => setComposerLlm(scope, id)}
          onWebChange={(id) => setComposerWeb(scope, id)}
          onSubmit={submit}
        />
      </div>
      {mentionDropdown && typeof document !== "undefined"
        ? createPortal(mentionDropdown, document.body)
        : null}
    </div>
  );
}
