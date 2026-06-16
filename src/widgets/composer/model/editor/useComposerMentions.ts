"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useState } from "react";
import type { MentionPos } from "@/widgets/composer/ui/ComposerMentionDropdown";
import { createChipElement, nextAttachId } from "@/widgets/composer/lib/composerChipUtils";
import { detectMentionFromSelection } from "@/widgets/composer/lib/composerEditorDom";
import { MAX_MENTION_RESULTS } from "@/widgets/composer/model/editor/constants";
import type { ComposerEditorRefs, MentionState } from "@/widgets/composer/model/editor/types";
import { attachmentPostTitle, postFreshness, postTitle } from "@/shared/lib/helpers";
import { useFloatingPanelScrollListeners } from "@/shared/lib/hooks/useFloatingPanelScrollListeners";
import { usePathname } from "next/navigation";

import { parseAppPath } from "@/shared/lib/routes";
import type { ComposerScope, Post } from "@/shared/types";

type Params = Pick<ComposerEditorRefs, "editorRef" | "inputBoxRef" | "mentionRef"> & {
  scope: ComposerScope;
  posts: Post[];
  attachedPostIds: string[];
  removeChipById: (id: string) => void;
  refreshIsEmpty: () => void;
  appendAttachment: (att: { id: string; kind: "post"; postId: string; title: string }) => void;
};

export function useComposerMentions({
  editorRef,
  inputBoxRef,
  mentionRef,
  scope,
  posts,
  attachedPostIds,
  removeChipById,
  refreshIsEmpty,
  appendAttachment,
}: Params) {
  const pathname = usePathname() ?? "/";
  const route = parseAppPath(pathname);
  const currentPostId = route.screen === "post" ? route.postId : null;
  const [mention, setMention] = useState<MentionState>(null);
  const [mentionIndex, setMentionIndex] = useState(0);
  const [mentionPos, setMentionPos] = useState<MentionPos | null>(null);

  const placement: "up" | "down" = scope === "home" ? "down" : "up";

  const mentionCandidates = useMemo<Post[]>(() => {
    const base = posts.filter((p) => {
      if (attachedPostIds.includes(p.id)) return false;
      if (scope === "post" && p.id === currentPostId) return false;
      return true;
    });
    return [...base].sort((a, b) => postFreshness(b) - postFreshness(a) || a.id.localeCompare(b.id));
  }, [posts, currentPostId, scope, attachedPostIds]);

  const mentionMatches = useMemo<Post[]>(() => {
    if (!mention) return [];
    const q = mention.query.trim().toLowerCase();
    if (!q) return mentionCandidates.slice(0, MAX_MENTION_RESULTS);
    return mentionCandidates
      .filter((p) => postTitle(p).toLowerCase().includes(q))
      .slice(0, MAX_MENTION_RESULTS);
  }, [mention, mentionCandidates]);

  useEffect(() => {
    setMentionIndex(0);
  }, [mention?.query, mentionMatches.length]);

  const clearMention = useCallback(() => setMention(null), []);

  const detectMention = useCallback((): MentionState => {
    const editor = editorRef.current;
    if (!editor) return null;
    return detectMentionFromSelection(editor);
  }, [editorRef]);

  const refreshMention = useCallback(() => {
    setMention(detectMention());
  }, [detectMention]);

  const pickMention = useCallback(
    (post: Post) => {
      if (!mention) return;
      const { textNode, atOffset, caretOffset } = mention;
      if (!editorRef.current?.contains(textNode)) return;
      const text = textNode.textContent || "";
      if (atOffset < 0 || atOffset > text.length || caretOffset < atOffset) return;
      const before = text.slice(0, atOffset);
      let after = text.slice(caretOffset);
      after = after.replace(/^;\s*/, "");
      textNode.textContent = before;
      const chip = createChipElement(
        {
          id: nextAttachId(),
          kind: "post",
          postId: post.id,
          title: attachmentPostTitle(post),
        },
        removeChipById,
      );
      const parent = textNode.parentNode;
      if (!parent) return;
      if (textNode.nextSibling) {
        parent.insertBefore(chip, textNode.nextSibling);
      } else {
        parent.appendChild(chip);
      }
      const spaceText = after.startsWith(" ") || after.startsWith("\u00A0") ? after : "\u00A0" + after;
      const tail = document.createTextNode(spaceText);
      if (chip.nextSibling) {
        parent.insertBefore(tail, chip.nextSibling);
      } else {
        parent.appendChild(tail);
      }
      const sel = window.getSelection();
      if (sel) {
        const range = document.createRange();
        range.setStart(tail, 1);
        range.collapse(true);
        sel.removeAllRanges();
        sel.addRange(range);
      }
      appendAttachment({
        id: chip.getAttribute("data-attach-id") as string,
        kind: "post",
        postId: post.id,
        title: attachmentPostTitle(post),
      });
      setMention(null);
      refreshIsEmpty();
    },
    [appendAttachment, editorRef, mention, refreshIsEmpty, removeChipById],
  );

  const updateMentionPos = useCallback(() => {
    const box = inputBoxRef.current;
    if (!box) return;
    const r = box.getBoundingClientRect();
    if (placement === "down") {
      setMentionPos({ mode: "down", top: r.bottom + 6, left: r.left, width: r.width });
    } else {
      setMentionPos({
        mode: "up",
        bottom: window.innerHeight - r.top + 6,
        left: r.left,
        width: r.width,
      });
    }
  }, [inputBoxRef, placement]);

  useLayoutEffect(() => {
    if (mention && mentionMatches.length > 0) updateMentionPos();
  }, [mention, mentionMatches.length, updateMentionPos]);

  const mentionOpen = !!mention && mentionMatches.length > 0;

  useFloatingPanelScrollListeners({
    open: mentionOpen,
    onReflow: updateMentionPos,
    onClose: clearMention,
  });

  useEffect(() => {
    if (!mentionOpen) return;
    const onDocMouseDown = (e: MouseEvent) => {
      const target = e.target as Node;
      if (editorRef.current?.contains(target)) return;
      if (mentionRef.current?.contains(target)) return;
      setMention(null);
    };
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, [editorRef, mentionOpen, mentionRef]);

  useEffect(() => {
    const onSelChange = () => {
      if (!editorRef.current) return;
      const sel = window.getSelection();
      if (!sel || sel.rangeCount === 0) return;
      const range = sel.getRangeAt(0);
      if (!editorRef.current.contains(range.startContainer)) return;
      refreshMention();
    };
    document.addEventListener("selectionchange", onSelChange);
    return () => document.removeEventListener("selectionchange", onSelChange);
  }, [editorRef, refreshMention]);

  return {
    mentionMatches,
    mentionIndex,
    mentionPos,
    mentionOpen,
    setMentionIndex,
    pickMention,
    refreshMention,
    clearMention,
  };
}
