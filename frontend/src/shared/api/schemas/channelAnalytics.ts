import { z } from "zod";

import { postReactionSchema } from "./post";

const channelTotalsSchema = z.object({
  subscribers: z.number(),
  reactions: z.number(),
  views: z.number(),
  comments: z.number(),
  reposts: z.number(),
  er: z.number(),
});

const channelDaySchema = z.object({
  date: z.string(),
  views: z.number(),
  posts: z.number(),
  subscribers: z.number(),
  reactions: z.number(),
  comments: z.number(),
  reposts: z.number(),
  er: z.number(),
});

export const channelHeatmapSchema = z.object({
  hours: z.array(z.string()),
  rows: z.array(z.object({ day: z.string(), values: z.array(z.number()) })),
  hasData: z.boolean().optional(),
});

const historySourceSchema = z.enum([
  "post_snapshots",
  "legacy_channel_snapshots",
  "mixed",
  "no_history",
  // legacy values kept for cached responses during rollout
  "publish_backfill",
  "snapshots",
]);

export const channelAnalyticsSummarySchema = z.object({
  startTotals: channelTotalsSchema,
  endTotals: channelTotalsSchema,
  subscribersAvailable: z.boolean().optional(),
  lastSnapshotAt: z.string().nullable().optional(),
  dataAgeSeconds: z.number().nullable().optional(),
  isStale: z.boolean().optional(),
});

export const channelAnalyticsTrendSchema = z.object({
  dayCount: z.number(),
  granularity: z.enum(["day", "30m"]),
  anchorDate: z.string(),
  days: z.array(channelDaySchema),
  historySource: historySourceSchema.optional(),
  trackingSince: z.string().nullable().optional(),
});

export const channelAnalyticsReactionsSchema = z.object({
  reactions: z.array(postReactionSchema),
});

export type ChannelAnalyticsHeatmap = z.infer<typeof channelHeatmapSchema>;

export const analyticsTopPostRowSchema = z.object({
  id: z.string(),
  title: z.string(),
  subscribers: z.number(),
  reactions: z.number(),
  views: z.number(),
  comments: z.number(),
  reposts: z.number(),
  er: z.number(),
});

export const channelAnalyticsTopPostsSchema = z.object({
  posts: z.array(analyticsTopPostRowSchema),
});

export type ChannelAnalyticsSummary = z.infer<typeof channelAnalyticsSummarySchema>;
export type ChannelAnalyticsTrend = z.infer<typeof channelAnalyticsTrendSchema>;
export type ChannelAnalyticsReactions = z.infer<typeof channelAnalyticsReactionsSchema>;
export type AnalyticsTopPostRow = z.infer<typeof analyticsTopPostRowSchema>;
