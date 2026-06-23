import { describe, expect, it } from "vitest";

import {
  MASKED_API_KEY,
  apiKeyForClientRequest,
  apiKeyForDisplay,
  formatApiKeyPreview,
  isApiKeyPreview,
  isCopyableApiKey,
  shouldMaskApiKeyInUi,
  canAttemptApiKeyCopy,
} from "@/shared/lib/profile/maskedApiKey";

describe("maskedApiKey", () => {
  it("formats preview as first3 + 10 stars + last3", () => {
    expect(formatApiKeyPreview("sk-real-secret-key")).toBe("sk-**********key");
  });

  it("detects preview token", () => {
    expect(isApiKeyPreview("sk-**********key")).toBe(true);
    expect(isApiKeyPreview(MASKED_API_KEY)).toBe(true);
    expect(isApiKeyPreview("sk-real-secret-key")).toBe(false);
  });

  it("masks real keys in display but keeps env refs visible", () => {
    expect(apiKeyForDisplay("sk-real-secret-key")).toBe("sk-**********key");
    expect(apiKeyForDisplay("env:OPENAI_API_KEY")).toBe("env:OPENAI_API_KEY");
    expect(apiKeyForDisplay("sk-real-secret-key", true)).toBe("sk-real-secret-key");
  });

  it("allows copy attempt for preview-only keys", () => {
    expect(canAttemptApiKeyCopy("sk-**********key")).toBe(true);
    expect(isCopyableApiKey("sk-**********key")).toBe(false);
  });

  it("omits preview from client requests", () => {
    expect(apiKeyForClientRequest("sk-**********key")).toBeUndefined();
    expect(apiKeyForClientRequest("sk-real")).toBe("sk-real");
  });

  it("shouldMaskApiKeyInUi for real secrets only", () => {
    expect(shouldMaskApiKeyInUi("sk-real")).toBe(true);
    expect(shouldMaskApiKeyInUi("env:OPENAI_API_KEY")).toBe(false);
  });
});
