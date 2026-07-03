/** Serialize PATCH mutations for one post so concurrent edits do not clobber each other. */
const tailByPostId = new Map<string, Promise<unknown>>();

export function enqueueSerialPostPatch<T>(
  postId: string,
  task: () => Promise<T>,
): Promise<T> {
  const previous = tailByPostId.get(postId) ?? Promise.resolve();
  const next = previous.catch(() => undefined).then(task);
  tailByPostId.set(postId, next);
  void next.finally(() => {
    if (tailByPostId.get(postId) === next) {
      tailByPostId.delete(postId);
    }
  });
  return next;
}
