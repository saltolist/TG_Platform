"use client";

import { useId } from "react";

/** Градиентный знак ✦: размер и сдвиг по вертикали задаются в CSS (`.sidebar-brand-star-svg`). */
export default function BrandStarIcon() {
  const gid = useId().replace(/:/g, "");
  const gradId = `sb-brand-grad-${gid}`;
  return (
    <svg className="sidebar-brand-star-svg" viewBox="0 0 24 24" aria-hidden="true">
      <defs>
        <linearGradient id={gradId} x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="var(--accent)" />
          <stop offset="100%" stopColor="var(--purple)" />
        </linearGradient>
      </defs>
      <path fill={`url(#${gradId})`} d="M12 3.25L19.25 12L12 20.75L4.75 12Z" />
    </svg>
  );
}
