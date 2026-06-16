"use client";

import type { ReactNode } from "react";

import {
  FEED_POST_WIDTH_SELECT_OPTIONS,
  isFeedPostWidth,
  type FeedPostWidth,
} from "@/shared/lib/feedPostWidth";
import { PageHeaderSearchInput, PageHeaderSelect } from "@/widgets/page-header";

export type FeedPostWidthSelectProps = {
  ariaLabel: string;
  value: string;
  options: typeof FEED_POST_WIDTH_SELECT_OPTIONS;
  onChange: (value: string) => void;
};

export type FeedHeaderSearchRowProps = {
  value: string;
  onChange: (value: string) => void;
  feedPostWidth: FeedPostWidth;
  onFeedPostWidthChange: (width: FeedPostWidth) => void;
  onSearchClose?: () => void;
  dismissAlways?: boolean;
};

export function buildFeedPostWidthSelectProps(
  feedPostWidth: FeedPostWidth,
  onFeedPostWidthChange: (width: FeedPostWidth) => void,
): FeedPostWidthSelectProps {
  return {
    ariaLabel: "Ширина карточки поста в ленте",
    value: String(feedPostWidth),
    options: FEED_POST_WIDTH_SELECT_OPTIONS,
    onChange: (v) => {
      const n = Number(v);
      if (isFeedPostWidth(n)) onFeedPostWidthChange(n);
    },
  };
}

/** Селектор ширины — в правой колонке (mobile / узкий desktop) и в mobileSelect. */
export function createFeedPostWidthSelect(
  props: Pick<FeedHeaderSearchRowProps, "feedPostWidth" | "onFeedPostWidthChange">,
): ReactNode {
  return <PageHeaderSelect {...buildFeedPostWidthSelectProps(props.feedPostWidth, props.onFeedPostWidthChange)} />;
}

/** Статическое JSX-дерево для PageHeader.search (нужно для expandable-поиска по лупе). */
export function createFeedHeaderSearchRow({
  value,
  onChange,
  feedPostWidth,
  onFeedPostWidthChange,
  onSearchClose,
  dismissAlways = false,
}: FeedHeaderSearchRowProps): ReactNode {
  const showDismissAlways = dismissAlways || !!onSearchClose;

  return (
    <div className="page-header-search-tools-row">
      <PageHeaderSearchInput
        placeholder="Поиск по постам..."
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onDismiss={onSearchClose ?? (() => onChange(""))}
        dismissAlways={showDismissAlways}
      />
      <div className="page-header-scope-select page-header-toolbar--desktop">
        <PageHeaderSelect {...buildFeedPostWidthSelectProps(feedPostWidth, onFeedPostWidthChange)} />
      </div>
    </div>
  );
}
