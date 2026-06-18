import type { ChatMessage } from "@/shared/types";

export function isStreamingChatMessage(message: ChatMessage | undefined): boolean {
  return message?.streaming === true;
}
