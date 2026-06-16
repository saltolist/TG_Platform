"use client";

import { Fragment, type CSSProperties } from "react";
import { formatChannelPostMetricValue } from "@/shared/lib/channelAnalyticsTrend";
import type { AnalyticsTopPostRow } from "@/shared/data/analyticsSeedData";
import type { AnalyticsScreenState } from "@/screens/analytics/model/useAnalyticsScreen";

type Props = {
  isMobile: boolean;
  posts: AnalyticsTopPostRow[];
  metrics: AnalyticsScreenState["data"]["topPostsTableMetrics"];
  wrapStyle: CSSProperties;
  gridStyle: CSSProperties;
  onOpenPost: (id: string) => void;
};

export default function AnalyticsTopPostsTable({
  isMobile,
  posts,
  metrics,
  wrapStyle,
  gridStyle,
  onOpenPost,
}: Props) {
  return (
    <div className="analytics-card analytics-top-posts-card platform-analytics-section">
      <div className="profile-section-title platform-section-title-spaced">Лучшие посты за период</div>
      <div className="analytics-top-posts-table-wrap" style={wrapStyle}>
        {isMobile ? (
          <table className="top-table analytics-top-posts-table">
            <colgroup>
              <col className="analytics-top-posts-col-title" />
              {metrics.map((metric) => (
                <col key={metric.id} className="analytics-top-posts-col-metric" />
              ))}
              <col className="analytics-top-posts-col-action" />
            </colgroup>
            <thead>
              <tr>
                <th>Пост</th>
                {metrics.map((metric) => (
                  <th key={metric.id}>{metric.label}</th>
                ))}
                <th className="analytics-top-posts-cell-action" aria-label="Открыть пост" />
              </tr>
            </thead>
            <tbody>
              {posts.map((post) => (
                <tr key={post.id}>
                  <td>{post.title}</td>
                  {metrics.map((metric) => (
                    <td key={metric.id}>
                      {formatChannelPostMetricValue(
                        metric.id,
                        post[metric.id as keyof AnalyticsTopPostRow] as number,
                      )}
                    </td>
                  ))}
                  <td className="analytics-top-posts-cell-action">
                    <span className="top-link" onClick={() => onOpenPost(post.id)}>
                      →
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="analytics-top-posts-grid top-table" role="table" style={gridStyle}>
            <div
              className="analytics-top-posts-grid-cell analytics-top-posts-grid-cell--title analytics-top-posts-grid-cell--head"
              role="columnheader"
            >
              Пост
            </div>
            {metrics.map((metric) => (
              <div
                key={metric.id}
                className="analytics-top-posts-grid-cell analytics-top-posts-grid-cell--metric analytics-top-posts-grid-cell--head"
                role="columnheader"
              >
                {metric.label}
              </div>
            ))}
            <div
              className="analytics-top-posts-grid-cell analytics-top-posts-grid-cell--action analytics-top-posts-grid-cell--head analytics-top-posts-cell-action"
              role="columnheader"
            >
              к посту
            </div>
            <div className="analytics-top-posts-grid-line" aria-hidden />
            {posts.map((post, rowIndex) => (
              <Fragment key={post.id}>
                <div
                  className="analytics-top-posts-grid-cell analytics-top-posts-grid-cell--title analytics-top-posts-grid-cell--body"
                  role="cell"
                >
                  {post.title}
                </div>
                {metrics.map((metric) => (
                  <div
                    key={`${post.id}-${metric.id}`}
                    className="analytics-top-posts-grid-cell analytics-top-posts-grid-cell--metric analytics-top-posts-grid-cell--body"
                    role="cell"
                  >
                    {formatChannelPostMetricValue(
                      metric.id,
                      post[metric.id as keyof AnalyticsTopPostRow] as number,
                    )}
                  </div>
                ))}
                <div
                  className="analytics-top-posts-grid-cell analytics-top-posts-grid-cell--action analytics-top-posts-grid-cell--body"
                  role="cell"
                >
                  <span className="top-link" onClick={() => onOpenPost(post.id)}>
                    →
                  </span>
                </div>
                {rowIndex < posts.length - 1 ? (
                  <div className="analytics-top-posts-grid-line" aria-hidden />
                ) : null}
              </Fragment>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
