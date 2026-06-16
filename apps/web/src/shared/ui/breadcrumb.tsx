"use client";

import type { ReactNode } from "react";

import { cn } from "@/shared/lib/utils";

export type BreadcrumbItem = {
  label: ReactNode;
  onClick?: () => void;
  href?: string;
  /** `title` — название поста (ellipsis в шапке поста); `truncate` — длинный заголовок заметки/чата. */
  variant?: "default" | "title" | "truncate";
  current?: boolean;
};

type BreadcrumbProps = {
  items: BreadcrumbItem[];
  className?: string;
};

export function breadcrumbItemClassName(
  item: BreadcrumbItem,
  index: number,
  isLast: boolean,
): string {
  const current = item.current ?? isLast;
  const parts: string[] = [];

  if (current) {
    parts.push("crumb-current");
  } else {
    parts.push("bc-link");
  }

  if (index === 0) {
    parts.push("bc-crumb-first");
  }

  if (item.variant === "title") {
    parts.push("bc-post-title");
  } else if (item.variant === "truncate") {
    parts.push("bc-crumb-truncate");
  } else {
    parts.push("bc-crumb-fixed");
  }

  return parts.join(" ");
}

export function Breadcrumb({ items, className }: BreadcrumbProps) {
  if (items.length === 0) return null;

  return (
    <nav
      className={cn("breadcrumb", className)}
      aria-label="Хлебные крошки"
    >
      {items.map((item, index) => {
        const isLast = index === items.length - 1;
        const cls = breadcrumbItemClassName(item, index, isLast);
        const key = `${index}-${typeof item.label === "string" ? item.label : "node"}`;

        return (
          <span key={key} style={{ display: "contents" }}>
            {index > 0 ? (
              <span className="bc-sep" aria-hidden="true">
                /
              </span>
            ) : null}
            {item.onClick && !isLast && !item.current ? (
              <button
                type="button"
                className={cls}
                onClick={item.onClick}
                aria-current={isLast ? "page" : undefined}
              >
                {item.label}
              </button>
            ) : (
              <span className={cls} aria-current={isLast || item.current ? "page" : undefined}>
                {item.label}
              </span>
            )}
          </span>
        );
      })}
    </nav>
  );
}
