import { z } from "zod";

export const platformModelUsageSchema = z.object({
  id: z.string(),
  label: z.string(),
  role: z.string(),
  type: z.string(),
  active: z.boolean(),
  calls: z.number(),
  tokens: z.number(),
  cost: z.number(),
  success: z.number(),
  latency: z.number(),
  share: z.number(),
  trend: z.array(z.number()),
});

export const platformActivitySchema = z.object({
  chats: z.number(),
  notes: z.number(),
  posts: z.number(),
});

export const platformModelAnalyticsSchema = z.object({
  models: z.array(platformModelUsageSchema),
  activity: platformActivitySchema,
});

export type PlatformModelUsageDto = z.infer<typeof platformModelUsageSchema>;
export type PlatformActivityDto = z.infer<typeof platformActivitySchema>;
export type PlatformModelAnalyticsDto = z.infer<typeof platformModelAnalyticsSchema>;
