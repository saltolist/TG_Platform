import { demoKanalPosts } from "@/shared/data/channel-pools/demo-kanal-posts";
import type { MswStore } from "@/shared/api/msw/store";

function cloneSeed<T>(value: T): T {
  return structuredClone(value);
}

/** Replaces account posts with the @demochannel Telegram feed snapshot. */
export function importDemoKanalContent(target: MswStore): number {
  target.posts = cloneSeed(demoKanalPosts);
  return target.posts.length;
}
