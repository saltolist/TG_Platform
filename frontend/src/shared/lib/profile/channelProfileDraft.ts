import type { ChannelProfileConfig } from "@/shared/types";

export function channelProfileBodySnapshot(cfg: ChannelProfileConfig): string {
  return JSON.stringify({ core: cfg.core, voice: cfg.voice, rules: cfg.rules });
}

export function isChannelProfileDraftDirty(
  current: ChannelProfileConfig,
  savedSnapshotJson: string,
): boolean {
  let saved: ChannelProfileConfig;
  try {
    saved = JSON.parse(savedSnapshotJson) as ChannelProfileConfig;
  } catch {
    return true;
  }
  if (channelProfileBodySnapshot(current) !== channelProfileBodySnapshot(saved)) {
    return true;
  }
  return JSON.stringify(current.rubrics) !== JSON.stringify(saved.rubrics);
}
