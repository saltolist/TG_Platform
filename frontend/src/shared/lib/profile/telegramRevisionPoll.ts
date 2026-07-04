import type { TelegramProfileConfig } from "@/shared/types";

export type TelegramRevisionBaselines = {
  syncRevision: number;
  commentsRevision: number;
  metricsRevision: number;
};

export type TelegramRevisionAdvance = {
  syncRevisionAdvanced: boolean;
  commentsRevisionAdvanced: boolean;
  metricsRevisionAdvanced: boolean;
  lastSyncAdvanced: boolean;
};

/** Compare polled telegram profile revisions against baselines captured *before* cache writes. */
export function detectTelegramRevisionAdvance(
  telegram: Partial<
    Pick<TelegramProfileConfig, "syncRevision" | "commentsRevision" | "metricsRevision" | "lastSync">
  >,
  baselines: TelegramRevisionBaselines,
  previousLastSync: string | null,
): TelegramRevisionAdvance {
  const syncRevision = telegram.syncRevision ?? 0;
  const commentsRevision = telegram.commentsRevision ?? 0;
  const metricsRevision = telegram.metricsRevision ?? 0;
  const lastSync = telegram.lastSync ?? "—";

  const lastSyncAdvanced =
    previousLastSync !== null &&
    lastSync !== "—" &&
    previousLastSync !== "—" &&
    lastSync !== previousLastSync;

  return {
    syncRevisionAdvanced: syncRevision > baselines.syncRevision,
    commentsRevisionAdvanced: commentsRevision > baselines.commentsRevision,
    metricsRevisionAdvanced: metricsRevision > baselines.metricsRevision,
    lastSyncAdvanced,
  };
}
