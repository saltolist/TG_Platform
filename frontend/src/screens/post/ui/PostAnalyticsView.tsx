"use client";

import { usePostAnalyticsScreen } from "@/screens/post/model/usePostAnalyticsScreen";
import PostGrowthSection from "@/screens/post/ui/PostGrowthSection";
import { EmptyState } from "@/shared/ui/empty-state";
import type { Post } from "@/shared/types";

export default function PostAnalyticsView({ post }: { post: Post }) {
  const analytics = usePostAnalyticsScreen(post.id, post.status === "published");

  const scrollClassName = "post-subpage-scroll post-analytics-scroll";

  if (post.status !== "published") {
    return (
      <div className={scrollClassName}>
        <div className="analytics-scroll-inner channel-growth-chart-context">
          <EmptyState
            message="Аналитика доступна только для опубликованных постов"
            className="min-h-[40vh]"
          />
        </div>
      </div>
    );
  }

  if (analytics.isLoading) {
    return (
      <div className={scrollClassName}>
        <div className="analytics-scroll-inner channel-growth-chart-context">
          <EmptyState message="Загрузка аналитики…" className="min-h-[40vh]" />
        </div>
      </div>
    );
  }

  return (
    <div className={scrollClassName}>
      <div className="analytics-scroll-inner channel-growth-chart-context">
        <PostGrowthSection
          periodIndex={analytics.periodIndex}
          periods={analytics.periods}
          onPeriodChange={analytics.onPeriodChange}
          labels={analytics.labels}
          series={analytics.series}
          historySource={analytics.historySource}
          trackingSince={analytics.trackingSince}
          isStale={analytics.isStale}
          dataAgeSeconds={analytics.dataAgeSeconds}
        />
      </div>
    </div>
  );
}
