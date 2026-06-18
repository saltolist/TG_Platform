"use client";

import type { ChatMessage as ChatMessageType } from "@/shared/types";
import { isStreamingChatMessage } from "@/shared/lib/streaming/streamingMessage";
import { ChatMessage } from "@/widgets/chat-thread";

type FlatRow = { message: ChatMessageType; path: number[] };

type GlobalChatMessagesProps = {
  chatId: string | null;
  flatMessages: FlatRow[];
  lastAssistantFlat: number;
  messagesRef: React.RefObject<HTMLDivElement | null>;
};

export function GlobalChatMessages({
  chatId,
  flatMessages,
  lastAssistantFlat,
  messagesRef,
}: GlobalChatMessagesProps) {
  if (!chatId) return null;

  return (
    <div className="composer-scroll-wrap">
      <div className="gchat-messages" ref={messagesRef}>
        <div className="composer-scroll-body">
          {flatMessages.map(({ message, path }, i) => {
            const nextMessage = flatMessages[i + 1]?.message;
            return (
              <ChatMessage
                key={path.join("-")}
                message={message}
                ctx={{ scope: "gchat", entityId: chatId, path }}
                isLastAssistantMessage={
                  message.role === "ai" && i === lastAssistantFlat && !isStreamingChatMessage(message)
                }
                isPendingUserTurn={
                  message.role === "user" && isStreamingChatMessage(nextMessage)
                }
              />
            );
          })}
        </div>
      </div>
    </div>
  );
}
