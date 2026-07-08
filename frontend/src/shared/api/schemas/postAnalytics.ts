import { z } from "zod";

import { channelAnalyticsTrendSchema } from "./channelAnalytics";

export const postAnalyticsTrendSchema = channelAnalyticsTrendSchema
  .omit({ historySource: true, subscribersAvailable: true })
  .extend({
    historySource: z.enum(["post_snapshots", "no_history"]).optional(),
    subscribersAvailable: z.literal(false).optional(),
    lastSnapshotAt: z.string().nullable().optional(),
    dataAgeSeconds: z.number().nullable().optional(),
    isStale: z.boolean().optional(),
  });

export type PostAnalyticsTrend = z.infer<typeof postAnalyticsTrendSchema>;
