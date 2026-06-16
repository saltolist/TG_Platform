"use client";

import { PageHeaderControl } from "@/shared/ui/page-header-tab-group";
import { cn } from "@/shared/lib/utils";

type BackButtonProps = {
  onClick: () => void;
  label?: string;
  className?: string;
};

/** Minimal left chevron — angular stroke, similar to ‹ but not a text glyph. */
export function BackChevronIcon({ className }: { className?: string }) {
  return (
    <svg
      className={cn("back-chevron-icon", className)}
      viewBox="0 0 16 16"
      width={11}
      height={11}
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.85}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M10.25 3.25 5.5 8l4.75 4.75" />
    </svg>
  );
}

export function BackButton({ onClick, label = "Назад", className }: BackButtonProps) {
  return (
    <PageHeaderControl
      type="button"
      className={cn("page-header-control--back", className)}
      onClick={onClick}
    >
      <BackChevronIcon />
      <span className="page-header-control-back-label">{label}</span>
    </PageHeaderControl>
  );
}
