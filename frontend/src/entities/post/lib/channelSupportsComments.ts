import type { TelegramProfileConfig } from "@/shared/types";

/** Channel-level: linked discussion group is enabled in Telegram profile. */
export function channelSupportsComments(
  telegram?: Pick<TelegramProfileConfig, "commentsEnabled" | "discussionChatId"> | null,
): boolean {
  return Boolean(telegram?.commentsEnabled && telegram?.discussionChatId);
}
