import type { AnalyticsTopPostRow } from "@/shared/data/analyticsSeedData";
import { parseViewsMetric } from "@/shared/data/analytics-seed";
import type { Post } from "@/shared/types";

function postTitle(text: string): string {
  const line = text.split("\n")[0]?.trim() ?? "Без названия";
  if (line.length <= 72) return line;
  return `${line.slice(0, 69)}…`;
}

function sumReactions(post: Post): number {
  return post.metrics?.reactions?.reduce((sum, item) => sum + item.count, 0) ?? 0;
}

export function buildAnalyticsTopPostsFromPosts(posts: Post[]): AnalyticsTopPostRow[] {
  return posts
    .filter((post) => post.status === "published")
    .map((post) => {
      const views = parseViewsMetric(post.metrics?.views);
      const reactions = sumReactions(post);
      const reposts = post.metrics?.reposts ?? 0;
      const comments = post.comments?.length ?? 0;
      const er = views > 0 ? ((reactions + comments) / views) * 100 : 0;
      const subscribers = Math.max(1, Math.round(views / 95));

      return {
        id: post.id,
        title: postTitle(post.text),
        subscribers,
        reactions,
        views,
        comments,
        reposts,
        er: Math.round(er * 10) / 10,
      };
    })
    .sort((a, b) => b.views - a.views);
}
