import { countVisibleChatMessages } from "@/shared/lib/chatPaths";
import type { GlobalChat, TelegramProfileConfig } from "@/shared/types";

export const OMNICHANNEL_CHAT_ID = "gc-omnichannel";

export function isOmnichannelChatId(id: string | null | undefined): boolean {
  return id === OMNICHANNEL_CHAT_ID;
}

export function isOmnichannelChat(chat: GlobalChat): boolean {
  return chat.kind === "omnichannel" || chat.id === OMNICHANNEL_CHAT_ID;
}

export { countVisibleChatMessages };

export function createOmnichannelChat(botUsername: string): GlobalChat {
  return {
    id: OMNICHANNEL_CHAT_ID,
    kind: "omnichannel",
    title: botUsername || "Омниканальный бот",
    preview: "",
    date: new Date().toISOString(),
    history: [],
  };
}

export function syncOmnichannelGlobalChats(
  globalChats: GlobalChat[],
  config: TelegramProfileConfig,
): GlobalChat[] {
  if (config.botStatus !== "connected") {
    return globalChats.filter((c) => !isOmnichannelChat(c));
  }
  const existing = globalChats.find((c) => isOmnichannelChat(c));
  const chat = existing ?? createOmnichannelChat(config.botUsername);
  const next: GlobalChat = {
    ...chat,
    title: config.botUsername || chat.title,
  };
  return [next, ...globalChats.filter((c) => !isOmnichannelChat(c))];
}
