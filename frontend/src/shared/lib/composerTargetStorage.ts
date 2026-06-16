export const COMPOSER_TARGET_STORAGE_PREFIX = "tg-platform-composer-target";

export type StoredComposerTarget = {
  llmId: string;
  webId: string;
};

export function composerTargetStorageKey(accountId: string): string {
  return `${COMPOSER_TARGET_STORAGE_PREFIX}:${accountId}`;
}

export function readStoredComposerTarget(accountId: string): StoredComposerTarget | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(composerTargetStorageKey(accountId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredComposerTarget>;
    return {
      llmId: typeof parsed.llmId === "string" ? parsed.llmId : "",
      webId: typeof parsed.webId === "string" ? parsed.webId : "",
    };
  } catch {
    return null;
  }
}

export function writeStoredComposerTarget(accountId: string, target: StoredComposerTarget): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(composerTargetStorageKey(accountId), JSON.stringify(target));
}
