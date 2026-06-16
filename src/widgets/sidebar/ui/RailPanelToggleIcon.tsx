"use client";

/** Иконка «панель с боковым столбцом» — сворачивание / разворачивание rail */
export default function RailPanelToggleIcon() {
  return (
    <svg className="sidebar-rail-toggle-svg" viewBox="0 0 24 24" width={18} height={18} aria-hidden="true">
      <rect x="4" y="5" width="16" height="14" rx="2.5" ry="2.5" fill="none" stroke="currentColor" strokeWidth={2} />
      <line x1="9.25" y1="8.25" x2="9.25" y2="15.75" stroke="currentColor" strokeWidth={2} strokeLinecap="round" />
    </svg>
  );
}
