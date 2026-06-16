"use client";

import { forwardRef } from "react";

import { useUiStore } from "@/app/model/store";

export const PageHeaderMenuButton = forwardRef<HTMLButtonElement>(function PageHeaderMenuButton(
  _,
  ref,
) {
  const setMobileSidebarOpen = useUiStore((s) => s.setMobileSidebarOpen);

  return (
    <button
      ref={ref}
      type="button"
      className="page-header-menu-btn"
      onClick={() => setMobileSidebarOpen(true)}
      aria-label="Открыть меню"
    >
      <svg className="page-header-menu-btn-icon" viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M5 7h14M5 12h14M5 17h14"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
        />
      </svg>
    </button>
  );
});
