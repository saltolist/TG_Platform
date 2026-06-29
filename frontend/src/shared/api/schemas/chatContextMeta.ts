import { z } from "zod";

const bundleGenerationSchema = z.object({
  id: z.string(),
  fingerprint: z.string(),
  text: z.string(),
  anchor_user_turn: z.number(),
});

const bundleProfileSchema = z.object({
  stub_generation_id: z.string().nullable().optional(),
  generations: z.array(bundleGenerationSchema).optional(),
});

const threadStateSchema = z.object({
  rolling_summary: z.string().optional(),
  rolling_summary_idx: z.number().optional(),
  rolling_summary_profile: bundleProfileSchema.optional(),
});

const pendingQueueItemSchema = z.object({
  version: z.number(),
  since_turn: z.number(),
});

const labelThreadStateSchema = z.object({
  head_version: z.number().optional(),
  pending_version: z.number().optional(),
  pending_since_turn: z.number().optional(),
  pending_queue: z.array(pendingQueueItemSchema).optional(),
  head_global: z.number().optional(),
  head_local: z.number().optional(),
  pending_global_version: z.number().optional(),
  pending_global_since_turn: z.number().optional(),
  pending_local_version: z.number().optional(),
  pending_local_since_turn: z.number().optional(),
  pending_global_queue: z.array(pendingQueueItemSchema).optional(),
  pending_local_queue: z.array(pendingQueueItemSchema).optional(),
  rolling_summary: z.string().optional(),
  rolling_summary_idx: z.number().optional(),
});

const stampPendingItemSchema = z.object({
  version: z.number(),
  sinceMsg: z.number(),
});

const stampBranchStateSchema = z.object({
  head: z.object({ channel: z.number(), post: z.number() }),
  pending: z.object({
    channel: z.array(stampPendingItemSchema).optional(),
    post: z.array(stampPendingItemSchema).optional(),
  }).optional(),
  rolling_summary: z.string().optional(),
  rolling_summary_idx: z.number().optional(),
});

const stampContextSchema = z.object({
  branches: z.record(z.string(), stampBranchStateSchema).optional(),
  next_branch_id: z.number().optional(),
  branch_registry: z.record(z.string(), z.number()).optional(),
});

export const chatContextMetaSchema = z.object({
  rolling_summary: z.string().optional(),
  rolling_summary_idx: z.number().optional(),
  rolling_summary_profile: bundleProfileSchema.optional(),
  active_thread_key: z.string().optional(),
  thread_context: z.record(z.string(), threadStateSchema).optional(),
  label_context: z.record(z.string(), labelThreadStateSchema).optional(),
  stamp_context: stampContextSchema.optional(),
  context_stamp_mechanics: z.boolean().optional(),
  active_branch: z.number().optional(),
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
  if (typeof source.active_thread_key === "string") {
    meta.active_thread_key = source.active_thread_key;
  }
  if (source.thread_context && typeof source.thread_context === "object") {
    meta.thread_context = source.thread_context;
  }
  if (source.label_context && typeof source.label_context === "object") {
    meta.label_context = source.label_context;
  }
  if (source.stamp_context && typeof source.stamp_context === "object") {
    meta.stamp_context = source.stamp_context;
  }
  if (typeof source.context_stamp_mechanics === "boolean") {
    meta.context_stamp_mechanics = source.context_stamp_mechanics;
  }
  if (typeof source.active_branch === "number") {
    meta.active_branch = source.active_branch;
  }
  return Object.keys(meta).length > 0 ? chatContextMetaSchema.parse(meta) : undefined;
}
