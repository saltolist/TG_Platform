"use client";

import ChatAiMessage from "./ChatAiMessage";
import ChatUserMessage from "./ChatUserMessage";
import type { ChatMessageCtx } from "@/entities/message";
import { useChatMessage } from "@/widgets/chat-thread/model/useChatMessage";
import type { ChatMessage as ChatMessageType } from "@/shared/types";

export type { ChatMessageCtx };

export default function ChatMessage({
  message,
  ctx,
  isLastAssistantMessage = false,
}: {
  message: ChatMessageType;
  ctx?: ChatMessageCtx;
  /** Показывать «Удалить» в меню только у последнего ответа ассистента в треде. */
  isLastAssistantMessage?: boolean;
}) {
  const chat = useChatMessage({ message, ctx });

  if (chat.isUser) {
    return (
      <ChatUserMessage
        ctx={ctx}
        textHtml={chat.textHtml}
        editing={chat.editing}
        draft={chat.draft}
        editSession={chat.editSession}
        copied={chat.copied}
        userActionsOpen={chat.userActionsOpen}
        userHoverZoneRef={chat.userHoverZoneRef}
        taRef={chat.taRef}
        userBranchCount={chat.userBranchCount}
        userBranchIdx={chat.userBranchIdx}
        onDraftChange={chat.setDraft}
        onEditKeyDown={chat.onEditKeyDown}
        onSave={chat.saveEdit}
        onCancel={chat.cancelEdit}
        onStartEdit={chat.startEdit}
        onCopy={chat.onCopyUser}
        onOpenMobileActions={chat.openUserActionsOnMobile}
        onBumpBranch={chat.bumpUserBranch}
      />
    );
  }

  return (
    <ChatAiMessage
      textHtml={chat.textHtml}
      plainAi={chat.plainAi}
      modelTitle={chat.modelTitle}
      ctx={ctx}
      showVariantNav={chat.aiVariantCount > 1}
      canGoVariantPrev={chat.aiVariantIdx > 0}
      canGoVariantNext={chat.aiVariantIdx < chat.aiVariantCount - 1}
      onBumpVariant={chat.bumpAiVariant}
      onDelete={ctx && isLastAssistantMessage ? chat.deleteMessage : undefined}
    />
  );
}
