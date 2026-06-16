import { postTitle } from "@/shared/lib/helpers";
import type { Post, PostMedia } from "@/shared/types";

export type AttachedMediaItem = { postId: string; media: PostMedia; postTitle: string };

let attachIdCounter = 0;

export function nextAttachMenuId(): string {
  attachIdCounter += 1;
  return `att-${Date.now()}-${attachIdCounter}`;
}

export function collectAttachedMedia(posts: Post[], attachedIds: string[]): AttachedMediaItem[] {
  return posts
    .filter((p) => attachedIds.includes(p.id))
    .flatMap((p) =>
      (p.media ?? []).map((m) => ({ postId: p.id, media: m, postTitle: postTitle(p) })),
    );
}
