import type { TelegramProfileConfig } from "@/shared/types";

export function isTelegramChannelConnected(
  cfg: TelegramProfileConfig | null | undefined,
): boolean {
  return cfg?.authStatus === "connected" && cfg?.channelStatus === "connected";
}
