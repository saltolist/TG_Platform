import type { ChannelMetricsDataset } from "@/shared/data/analytics-seed";
import { parseViewsMetric } from "@/shared/data/analytics-seed";
import type { Post, PostReaction } from "@/shared/types";

import { buildAnalyticsTopPostsFromPosts } from "./buildTopPostsFromPosts";

const PERIOD_DAYS: Record<string, number | null> = {
  "24h": 1,
  "7d": 7,
  "30d": 30,
  "90d": 90,
  all: null,
};

function postDate(post: Post): Date | null {
  const raw = post.date;
  if (!raw) return null;
  const parsed = new Date(raw);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function sumReactions(post: Post): number {
  return post.metrics?.reactions?.reduce((sum, item) => sum + item.count, 0) ?? 0;
}

function calcEr(views: number, reactions: number, comments: number): number {
  if (views <= 0) return 0;
  return Math.round(((reactions + comments) / views) * 1000) / 10;
}

function totalsFromPosts(posts: Post[]) {
  let views = 0;
  let reactions = 0;
  let comments = 0;
  let reposts = 0;
  for (const post of posts) {
    views += parseViewsMetric(post.metrics?.views);
    reactions += sumReactions(post);
    reposts += post.metrics?.reposts ?? 0;
    comments += post.comments?.length ?? 0;
  }
  return {
    subscribers: views > 0 ? Math.max(1, Math.round(views / 95)) : 0,
    reactions,
    views,
    comments,
    reposts,
    er: calcEr(views, reactions, comments),
  };
}

function periodDaySpan(period: string, published: Post[]): number {
  if (period !== "all") return PERIOD_DAYS[period] ?? 30;
  const dates = published.map(postDate).filter((d): d is Date => d !== null);
  if (dates.length === 0) return 30;
  const earliest = new Date(Math.min(...dates.map((d) => d.getTime())));
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  earliest.setHours(0, 0, 0, 0);
  const span = Math.floor((today.getTime() - earliest.getTime()) / 86_400_000) + 1;
  return Math.min(Math.max(span, 7), 110);
}

function postsInWindow(published: Post[], period: string): Post[] {
  if (period === "all") return published;
  const daySpan = periodDaySpan(period, published);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const start = new Date(today);
  start.setDate(start.getDate() - (daySpan - 1));
  return published.filter((post) => {
    const date = postDate(post);
    if (!date) return false;
    const day = new Date(date);
    day.setHours(0, 0, 0, 0);
    return day >= start && day <= today;
  });
}

function aggregateReactions(posts: Post[]): PostReaction[] {
  const counts = new Map<string, number>();
  for (const post of posts) {
    for (const item of post.metrics?.reactions ?? []) {
      counts.set(item.emoji, (counts.get(item.emoji) ?? 0) + item.count);
    }
  }
  return [...counts.entries()]
    .map(([emoji, count]) => ({ emoji, count }))
    .sort((a, b) => b.count - a.count);
}

export function buildChannelOverviewFromPosts(
  posts: Post[],
  period: string,
): ChannelMetricsDataset & { reactions: PostReaction[] } {
  const published = posts.filter((post) => post.status === "published");
  const windowPosts = postsInWindow(published, period);
  const daySpan = periodDaySpan(period, published);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const startDay = new Date(today);
  startDay.setDate(startDay.getDate() - (daySpan - 1));

  const endTotals = totalsFromPosts(published);
  const windowTotals = totalsFromPosts(windowPosts);
  const startTotals = {
    subscribers: Math.max(0, endTotals.subscribers - windowTotals.subscribers),
    reactions: Math.max(0, endTotals.reactions - windowTotals.reactions),
    views: Math.max(0, endTotals.views - windowTotals.views),
    comments: Math.max(0, endTotals.comments - windowTotals.comments),
    reposts: Math.max(0, endTotals.reposts - windowTotals.reposts),
    er: Math.max(0, Math.round((endTotals.er - windowTotals.er) * 10) / 10),
  };

  const days = Array.from({ length: daySpan }, (_, offset) => {
    const day = new Date(startDay);
    day.setDate(day.getDate() + offset);
    const dayPosts = windowPosts.filter((post) => {
      const postDay = postDate(post);
      if (!postDay) return false;
      const normalized = new Date(postDay);
      normalized.setHours(0, 0, 0, 0);
      return normalized.getTime() === day.getTime();
    });
    const dayTotals = totalsFromPosts(dayPosts);
    return {
      date: day.toISOString().slice(0, 10),
      views: dayTotals.views,
      posts: dayPosts.length,
      subscribers: dayTotals.subscribers,
      reactions: dayTotals.reactions,
      comments: dayTotals.comments,
      reposts: dayTotals.reposts,
      er: dayTotals.er,
    };
  });

  return {
    version: 1,
    dayCount: daySpan,
    startTotals,
    endTotals,
    days,
    reactions: aggregateReactions(published),
  };
}

export function buildChannelTopPostsFromPosts(posts: Post[], period: string) {
  const published = posts.filter((post) => post.status === "published");
  const windowPosts = postsInWindow(published, period);
  const ranked = buildAnalyticsTopPostsFromPosts(windowPosts);
  const allowed = new Set(windowPosts.map((post) => post.id));
  return ranked.filter((row) => allowed.has(row.id));
}
