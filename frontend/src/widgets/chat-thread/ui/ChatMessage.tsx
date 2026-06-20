"use client";

import ChatAiMessage from "./ChatAiMessage";
import ChatUserMessage from "./ChatUserMessage";
import type { ChatMessageCtx } from "@/entities/message";
import { useChatMessage } from "@/widgets/chat-thread/model/useChatMessage";
import { isStreamingChatMessage } from "@/shared/lib/streaming/streamingMessage";
import type { ChatMessage as ChatMessageType } from "@/shared/types";

export type { ChatMessageCtx };

export default function ChatMessage({
  message,
  ctx,
  isLastAssistantMessage = false,
  isPendingUserTurn = false,
  lockUserEdit = false,
  lockDelete = false,
}: {
  message: ChatMessageType;
  ctx?: ChatMessageCtx;
  /** Показывать «Удалить» в меню только у последнего ответа ассистента в треде. */
  isLastAssistantMessage?: boolean;
  /** Сообщение пользователя перед стримингом ответа — скрыть редактирование. */
  isPendingUserTurn?: boolean;
  /** Первое user-сообщение в чате — без редактирования. */
  lockUserEdit?: boolean;
  /** User-turn выше имеет ветки — без удаления ответа ассистента. */
  lockDelete?: boolean;
}) {
  const chat = useChatMessage({ message, ctx });
  const isStreaming = isStreamingChatMessage(message);

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
        lockUserActions={isPendingUserTurn}
        canEdit={!lockUserEdit}
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
      onDelete={
        ctx && isLastAssistantMessage && !isStreaming && !lockDelete
          ? chat.deleteMessage
          : undefined
      }
      isStreaming={isStreaming}
    />
  );
}
