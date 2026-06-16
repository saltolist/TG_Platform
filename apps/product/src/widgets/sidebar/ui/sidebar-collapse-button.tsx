"use client";

type SidebarCollapseButtonProps = {
  onClick: () => void;
};

export function SidebarCollapseButton({ onClick }: SidebarCollapseButtonProps) {
  return (
    <button
      type="button"
      className="sidebar-collapse-btn"
      onClick={onClick}
      aria-label="Свернуть панель"
      title="Свернуть панель"
    >
      <span className="sidebar-collapse-btn-inner" aria-hidden>
        <svg className="sidebar-rail-toggle-svg" viewBox="0 0 24 24" width={18} height={18}>
          <path
            d="M9 6l6 6-6 6"
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </span>
    </button>
  );
}
