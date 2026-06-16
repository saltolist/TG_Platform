"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { useNavigationStore } from "@/app/model/store/navigation-store";
import { useChatMessageActions } from "@/features/edit-chat-message";
import {
  USER_EDIT_MAX_W,
  assistantPlainText,
  copyPlainText,
  measureUserEditTextWidth,
  messageTextHtml,
  modelTooltipText,
  type ChatMessageCtx,
} from "@/entities/message";
import { useMobile760 } from "@/shared/lib/hooks/useMobile760";
import { clampActiveBranchIndex, displayUserText } from "@/shared/lib/chatPaths";
import { isOmnichannelChatId } from "@/shared/lib/omnichannel";
import {
  confirmDiscardAnyChatEdit,
  discardUserMessageEdit,
  registerUserMessageEdit,
  unregisterUserMessageEdit,
} from "@/shared/lib/userMessageEditSession";
import type { ChatMessage as ChatMessageType } from "@/shared/types";

type Props = {
  message: ChatMessageType;
  ctx?: ChatMessageCtx;
};

export function useChatMessage({ message, ctx }: Props) {
  const { saveUserMessage, setUserBranch, setAiVariant, deleteMessage } = useChatMessageActions();
  const isPostEditing = useNavigationStore((s) => s.isEditing);

  const isUser = message.role === "user";
  const userShown = displayUserText(message);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(userShown);
  const [copied, setCopied] = useState(false);
  const [editSession, setEditSession] = useState(0);
  const [userActionsOpen, setUserActionsOpen] = useState(false);

  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const userHoverZoneRef = useRef<HTMLDivElement>(null);
  const isMobile = useMobile760();
  const pathKey = ctx ? ctx.path.join("-") : "";

  useEffect(() => {
    if (!editing) setDraft(userShown);
  }, [userShown, editing]);

  useEffect(() => {
    return () => {
      if (copyTimer.current) clearTimeout(copyTimer.current);
    };
  }, []);

  useEffect(() => {
    if (!isMobile) setUserActionsOpen(false);
  }, [isMobile]);

  useEffect(() => {
    if (!isMobile || !userActionsOpen || editing) return;
    const onPointerDown = (event: PointerEvent) => {
      if (userHoverZoneRef.current?.contains(event.target as Node)) return;
      setUserActionsOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown, true);
    return () => document.removeEventListener("pointerdown", onPointerDown, true);
  }, [isMobile, userActionsOpen, editing]);

  const openUserActionsOnMobile = useCallback(() => {
    if (!isMobile || !ctx || editing) return;
    setUserActionsOpen(true);
  }, [isMobile, ctx, editing]);

  useEffect(() => {
    if (editing && taRef.current) {
      taRef.current.focus();
      const len = taRef.current.value.length;
      taRef.current.setSelectionRange(len, len);
    }
  }, [editing]);

  useLayoutEffect(() => {
    const ta = taRef.current;
    if (!editing) {
      if (ta) {
        ta.style.width = "";
        ta.style.height = "";
        ta.style.overflowY = "";
      }
      return;
    }
    if (!ta) return;
    const cap = 360;
    ta.style.width = "0px";
    const textW = measureUserEditTextWidth(draft, ta, USER_EDIT_MAX_W);
    ta.style.width = `${textW}px`;
    ta.style.height = "auto";
    const sh = ta.scrollHeight;
    ta.style.height = `${Math.min(sh, cap)}px`;
    ta.style.overflowY = sh > cap ? "auto" : "hidden";
  }, [draft, editing, pathKey, editSession]);

  const textHtml = messageTextHtml(message, userShown);
  const plainAi = assistantPlainText(message);
  const modelTitle = modelTooltipText(message);

  let aiVariantCount = 0;
  let aiVariantIdx = 0;
  if (!isUser && Array.isArray(message.variants) && message.variants.length > 0) {
    aiVariantCount = message.variants.length;
    aiVariantIdx = Math.min(
      Math.max(Number(message.selectedVariant) || 0, 0),
      message.variants.length - 1,
    );
  }

  const onCopyUser = useCallback(async () => {
    const ok = await copyPlainText(userShown);
    if (!ok) return;
    if (copyTimer.current) clearTimeout(copyTimer.current);
    setCopied(true);
    copyTimer.current = setTimeout(() => {
      setCopied(false);
      copyTimer.current = null;
    }, 2000);
  }, [userShown]);

  const cancelEdit = useCallback(() => {
    setEditing(false);
    setDraft(userShown);
  }, [userShown]);

  useEffect(() => {
    if (!editing || !isUser || !ctx) return;
    registerUserMessageEdit(cancelEdit);
    return () => unregisterUserMessageEdit(cancelEdit);
  }, [editing, isUser, ctx, cancelEdit]);

  const startEdit = useCallback(() => {
    void (async () => {
      if (!ctx) return;
      if (!editing) {
        if (!(await confirmDiscardAnyChatEdit(isPostEditing))) return;
        discardUserMessageEdit();
      }
      setDraft(userShown);
      setEditSession((n) => n + 1);
      setUserActionsOpen(false);
      setEditing(true);
    })();
  }, [ctx, userShown, editing, isPostEditing]);

  const saveEdit = useCallback(() => {
    if (!ctx) return;
    const text = draft.trim();
    if (text === "") return;
    saveUserMessage(ctx, ctx.path, text);
    setEditing(false);
  }, [ctx, draft, saveUserMessage]);

  const onEditKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        saveEdit();
      }
    },
    [saveEdit],
  );

  const omnichannelEdit = ctx?.scope === "gchat" && isOmnichannelChatId(ctx.entityId);
  const userBranchCount = omnichannelEdit ? 0 : (message.userBranches?.length ?? 0);
  const userBranchIdx = isUser && userBranchCount > 0 ? clampActiveBranchIndex(message) : 0;

  const bumpUserBranch = useCallback(
    (delta: number) => {
      if (!ctx || userBranchCount < 2) return;
      const next = (userBranchIdx + delta + userBranchCount) % userBranchCount;
      setUserBranch(ctx, ctx.path, next);
    },
    [ctx, setUserBranch, userBranchCount, userBranchIdx],
  );

  const bumpAiVariant = useCallback(
    (delta: number) => {
      if (!ctx || aiVariantCount < 2) return;
      const next = aiVariantIdx + delta;
      if (next < 0 || next >= aiVariantCount) return;
      setAiVariant(ctx, ctx.path, next);
    },
    [ctx, setAiVariant, aiVariantCount, aiVariantIdx],
  );

  const onDeleteMessage = useCallback(() => {
    if (!ctx) return;
    deleteMessage(ctx, ctx.path);
  }, [ctx, deleteMessage]);

  return {
    isUser,
    textHtml,
    plainAi,
    modelTitle,
    editing,
    draft,
    setDraft,
    copied,
    editSession,
    userActionsOpen,
    taRef,
    userHoverZoneRef,
    onCopyUser,
    startEdit,
    saveEdit,
    cancelEdit,
    onEditKeyDown,
    openUserActionsOnMobile,
    userBranchCount,
    userBranchIdx,
    bumpUserBranch,
    aiVariantCount,
    aiVariantIdx,
    bumpAiVariant,
    deleteMessage: onDeleteMessage,
  };
}
