import type { TelegramProfileConfig } from "@/shared/types";

/** Merge live-sync fields from a polled telegram profile into local draft state. */
export function mergeTelegramSyncFields(
  current: TelegramProfileConfig,
  telegram: TelegramProfileConfig,
): TelegramProfileConfig {
  return {
    ...current,
    importStatus: telegram.importStatus,
    importError: telegram.importError,
    importedPosts: telegram.importedPosts,
    lastSync: telegram.lastSync,
    syncStatus: telegram.syncStatus,
    syncError: telegram.syncError,
    syncRevision: telegram.syncRevision,
    commentsRevision: telegram.commentsRevision,
    metricsRevision: telegram.metricsRevision,
    commentsEnabled: telegram.commentsEnabled,
    discussionChatId: telegram.discussionChatId,
  };
}
