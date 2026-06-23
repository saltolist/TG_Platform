/** Legacy mask token (older backend responses). */
export const MASKED_API_KEY = "__masked__";

export const API_KEY_PREVIEW_STAR_COUNT = 10;

const ENV_REF_PREFIX = "env:";

export function formatApiKeyPreview(plaintext: string): string {
  if (!plaintext) return "";
  const stars = "*".repeat(API_KEY_PREVIEW_STAR_COUNT);
  if (plaintext.length >= 6) {
    return plaintext.slice(0, 3) + stars + plaintext.slice(-3);
  }
  if (plaintext.length <= 3) {
    return plaintext.padEnd(3, "*") + stars + plaintext.slice(-3).padStart(3, "*");
  }
  return plaintext.slice(0, 3) + stars + plaintext.slice(-3);
}

export function isApiKeyPreview(value: string | undefined | null): boolean {
  if (!value) return false;
  if (value === MASKED_API_KEY) return true;
  const marker = "*".repeat(API_KEY_PREVIEW_STAR_COUNT);
  const pos = value.indexOf(marker);
  return pos > 0 && pos <= 3;
}

/** @deprecated use isApiKeyPreview */
export function isMaskedApiKey(value: string | undefined | null): boolean {
  return isApiKeyPreview(value);
}

/** True when the UI should show stars instead of the full secret. */
export function shouldMaskApiKeyInUi(value: string | undefined | null): boolean {
  if (!value || isApiKeyPreview(value)) return false;
  if (value.startsWith(ENV_REF_PREFIX)) return false;
  return value.length >= 4;
}

/** Masked display in the input; full value stays in model state for save/copy. */
export function apiKeyForDisplay(
  value: string | undefined | null,
  editing = false,
): string {
  if (!value || editing) return value ?? "";
  if (shouldMaskApiKeyInUi(value)) return formatApiKeyPreview(value);
  return value;
}

/** Omit preview / legacy mask from outbound AI requests. */
export function apiKeyForClientRequest(value: string | undefined | null): string | undefined {
  const trimmed = (value ?? "").trim();
  if (!trimmed || isApiKeyPreview(trimmed)) return undefined;
  return trimmed;
}

export function isEditableApiKey(value: string | undefined | null): boolean {
  return !!value && !isApiKeyPreview(value);
}

export function isCopyableApiKey(value: string | undefined | null): boolean {
  const trimmed = (value ?? "").trim();
  if (!trimmed) return false;
  return !isApiKeyPreview(trimmed);
}

/** Whether the copy button should be enabled (includes preview-only keys). */
export function canAttemptApiKeyCopy(value: string | undefined | null): boolean {
  return !!(value ?? "").trim();
}
