"use client";

type SidebarChevronProps = {
  expanded: boolean;
  label: string;
  onToggle: () => void;
};

export function SidebarChevron({ expanded, label, onToggle }: SidebarChevronProps) {
  return (
    <button
      type="button"
      className={`nav-chats-chevron${expanded ? " is-expanded" : " is-collapsed"}`}
      aria-expanded={expanded}
      aria-label={label}
      onClick={(e) => {
        e.stopPropagation();
        onToggle();
      }}
    >
      <svg
        className="nav-chats-chevron-svg"
        viewBox="0 0 24 24"
        aria-hidden="true"
        fill="none"
        stroke="currentColor"
        strokeWidth={2.4}
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <polyline points="6 9 12 15 18 9" />
      </svg>
    </button>
  );
}
