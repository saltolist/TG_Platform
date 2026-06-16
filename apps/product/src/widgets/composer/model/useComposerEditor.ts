"use client";

import { useCallback, useMemo, useRef } from "react";
import { useComposerChips } from "@/widgets/composer/model/editor/useComposerChips";
import { useComposerKeyboard } from "@/widgets/composer/model/editor/useComposerKeyboard";
import { useComposerMentions } from "@/widgets/composer/model/editor/useComposerMentions";
import { useComposerModelTarget } from "@/widgets/composer/model/editor/useComposerModelTarget";
import { useComposerLayout } from "@/widgets/composer/model/editor/useComposerPlaceholder";
import type { UseComposerEditorProps } from "@/widgets/composer/model/editor/types";
import { usePosts } from "@/entities/post";
import { useComposerSubmit } from "@/widgets/composer/model/useComposerSubmit";

export function useComposerEditor({ scope, placeholder, onSubmit }: UseComposerEditorProps) {
  const { data: posts = [] } = usePosts();
  const modelTarget = useComposerModelTarget(scope);
  const { narrowComposer, effectivePlaceholder } = useComposerLayout(placeholder);

  const editorRef = useRef<HTMLDivElement>(null);
  const inputBoxRef = useRef<HTMLDivElement>(null);
  const mentionRef = useRef<HTMLDivElement>(null);

  const chips = useComposerChips({ editorRef });
  const {
    attachments,
    isEmpty,
    refreshIsEmpty,
    normalizeEmptyEditorFocus,
    removeChipById,
    addAttachmentInline,
    appendAttachment,
    serializeEditor,
    clearEditorContent,
    syncAttachmentsFromDom,
  } = chips;

  const attachedPostIds = useMemo(
    () =>
      attachments
        .filter((a): a is Extract<(typeof attachments)[number], { kind: "post" }> => a.kind === "post")
        .map((a) => a.postId),
    [attachments],
  );

  const mentions = useComposerMentions({
    editorRef,
    inputBoxRef,
    mentionRef,
    scope,
    posts,
    attachedPostIds,
    removeChipById,
    refreshIsEmpty,
    appendAttachment,
  });

  const { clearMention, mentionMatches, mentionIndex, mentionPos, mentionOpen, setMentionIndex, pickMention, refreshMention } =
    mentions;

  const clearEditor = useCallback(() => {
    clearEditorContent();
    clearMention();
  }, [clearEditorContent, clearMention]);

  const submit = useComposerSubmit(serializeEditor, clearEditor, onSubmit);

  const keyboard = useComposerKeyboard({
    narrowComposer,
    mentionOpen,
    mentionMatches,
    mentionIndex,
    setMentionIndex,
    pickMention,
    clearMention,
    submit,
    refreshIsEmpty,
    refreshMention,
    syncAttachmentsFromDom,
  });

  const placement: "up" | "down" = scope === "home" ? "down" : "up";
  const maxLines = scope === "home" ? 10 : 16;

  return {
    scope,
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
    llmOptions: modelTarget.llmOptions,
    webOptions: modelTarget.webOptions,
    llmId: modelTarget.llmId,
    webId: modelTarget.webId,
    isMulti: modelTarget.isMulti,
    setComposerLlm: modelTarget.setComposerLlm,
    setComposerWeb: modelTarget.setComposerWeb,
    setMentionIndex,
    addAttachmentInline,
    pickMention,
    onEditorInput: keyboard.onEditorInput,
    onKeyDown: keyboard.onKeyDown,
    onPaste: keyboard.onPaste,
    normalizeEmptyEditorFocus,
    refreshMention,
    submit,
  };
}
