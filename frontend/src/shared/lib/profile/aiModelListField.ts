import type { AiProfileConfig } from "@/shared/types";

/** JSON field name in ``AiProfileConfig`` that holds a model list with ``apiKey``. */
export type AiModelListField = {
  [K in keyof AiProfileConfig]: AiProfileConfig[K] extends infer V
    ? V extends Array<{ apiKey: string }>
      ? K
      : never
    : never;
}[keyof AiProfileConfig];

export type RevealAiModelApiKeyResponse = {
  apiKey: string;
};
