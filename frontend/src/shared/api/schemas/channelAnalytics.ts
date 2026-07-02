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

export const channelAnalyticsOverviewSchema = z.object({
  version: z.literal(1),
  dayCount: z.number(),
  startTotals: channelTotalsSchema,
  endTotals: channelTotalsSchema,
  days: z.array(channelDaySchema),
  reactions: z.array(postReactionSchema),
});

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
