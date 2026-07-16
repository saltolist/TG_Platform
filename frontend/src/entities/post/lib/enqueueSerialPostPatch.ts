import { runExclusive } from "@/shared/lib/asyncMutex";

/**
 * Serialize PATCH mutations for one post so concurrent edits do not clobber
 * each other. Shares the `post:{id}` mutex key with patchPostChatHistory, so
 * comment edits and chat-history/proposal writes queue together rather than
 * racing on the same post object.
 */
export function enqueueSerialPostPatch<T>(
  postId: string,
  task: () => Promise<T>,
): Promise<T> {
  return runExclusive(`post:${postId}`, task);
}
