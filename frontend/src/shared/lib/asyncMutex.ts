// Keyed async mutex: serializes read-modify-write cycles that share a resource.
//
// Two independent SSE-driven flows patch the same post/chat history object
// (composer-store finalize + agent-run-store proposal persist). Each does a
// fetchQuery → transform → update round-trip; with React Query's 60s staleTime
// the concurrent fetches return the SAME snapshot, so the last update wins and
// silently drops the other's change (a lost HITL proposal card). Funnelling
// both through runExclusive(key) forces the second writer to start only after
// the first has refreshed the cache, so it reads the merged result.

const chains = new Map<string, Promise<unknown>>();

/**
 * Run `fn` so that no two calls sharing `key` overlap. Calls with different
 * keys run concurrently. The returned promise resolves/rejects with `fn`'s
 * result; a rejection does not break the chain for later callers.
 */
export function runExclusive<T>(key: string, fn: () => Promise<T>): Promise<T> {
  const prev = chains.get(key) ?? Promise.resolve();
  // Swallow the predecessor's rejection here so one failure can't reject every
  // queued caller; each caller still sees its own fn's outcome via `result`.
  const result = prev.catch(() => undefined).then(() => fn());
  // Keep the chain tail pointing at this call until it settles, then clean up
  // if nothing else queued behind it — avoids leaking a Map entry per key.
  const tail = result.catch(() => undefined);
  chains.set(key, tail);
  void tail.then(() => {
    if (chains.get(key) === tail) chains.delete(key);
  });
  return result;
}
