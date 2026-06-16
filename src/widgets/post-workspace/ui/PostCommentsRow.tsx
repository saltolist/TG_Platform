"use client";

import type { MouseEvent } from "react";

function CommentsChevron() {
  return (
    <svg
      className="post-comments-chevron"
      viewBox="0 0 24 24"
      width={16}
      height={16}
      aria-hidden
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <polyline points="9 18 15 12 9 6" />
    </svg>
  );
}

type Props = {
  count: number;
  onClick?: (e: MouseEvent) => void;
};

export default function PostCommentsRow({ count, onClick }: Props) {
  const className = `post-comments-row${onClick ? " post-comments-row--action" : ""}`;
  const content = (
    <>
      <span className="post-comments-row-text">Комментарии</span>
      <span className="post-comments-count">{count}</span>
      {onClick ? <CommentsChevron /> : null}
    </>
  );

  if (onClick) {
    return (
      <button type="button" className={className} onClick={onClick}>
        {content}
      </button>
    );
  }

  return <div className={className}>{content}</div>;
}
