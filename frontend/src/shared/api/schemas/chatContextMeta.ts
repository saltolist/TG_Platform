import { z } from "zod";

export const chatContextMetaSchema = z.object({
  rolling_summary: z.string().optional(),
  rolling_summary_idx: z.number().optional(),
  rolling_summary_profile: z
    .object({
      stub_generation_id: z.string().nullable().optional(),
      generations: z
        .array(
          z.object({
            id: z.string(),
            fingerprint: z.string(),
            text: z.string(),
            anchor_user_turn: z.number(),
          }),
        )
        .optional(),
    })
    .optional(),
});

export type ChatContextMeta = z.infer<typeof chatContextMetaSchema>;

export function extractChatContextMeta(
  source: Record<string, unknown> | null | undefined,
): ChatContextMeta | undefined {
  if (!source) return undefined;
  const meta: Record<string, unknown> = {};
  if (typeof source.rolling_summary === "string") meta.rolling_summary = source.rolling_summary;
  if (typeof source.rolling_summary_idx === "number") {
    meta.rolling_summary_idx = source.rolling_summary_idx;
  }
  if (source.rolling_summary_profile && typeof source.rolling_summary_profile === "object") {
    meta.rolling_summary_profile = source.rolling_summary_profile;
  }
  return Object.keys(meta).length > 0 ? chatContextMetaSchema.parse(meta) : undefined;
}
