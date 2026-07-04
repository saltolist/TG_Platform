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

const channelHeatmapSchema = z.object({
  hours: z.array(z.string()),
  rows: z.array(z.object({ day: z.string(), values: z.array(z.number()) })),
  hasData: z.boolean().optional(),
});

export const channelAnalyticsOverviewSchema = z.object({
  version: z.union([z.literal(1), z.literal(2)]),
  dayCount: z.number(),
  startTotals: channelTotalsSchema,
  endTotals: channelTotalsSchema,
  days: z.array(channelDaySchema),
  reactions: z.array(postReactionSchema),
  // v2 (real history from snapshots)
  granularity: z.enum(["day", "30m"]).optional(),
  anchorDate: z.string().optional(),
  subscribersAvailable: z.boolean().optional(),
  heatmap: channelHeatmapSchema.optional(),
  historySource: z.enum(["publish_backfill", "snapshots", "mixed"]).optional(),
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

export type ChannelAnalyticsOverview = z.infer<typeof channelAnalyticsOverviewSchema>;
export type AnalyticsTopPostRow = z.infer<typeof analyticsTopPostRowSchema>;
