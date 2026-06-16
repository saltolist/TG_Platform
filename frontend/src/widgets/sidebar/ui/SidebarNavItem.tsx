"use client";

import type { ReactNode } from "react";

type SidebarNavItemProps = {
  id: string;
  label: string;
  icon: ReactNode;
  active?: boolean;
  onClick: () => void;
  as?: "div" | "button";
};

export function SidebarNavItem({
  id,
  label,
  icon,
  active = false,
  onClick,
  as = "div",
}: SidebarNavItemProps) {
  const className = `nav-item${active ? " active" : ""}`;
  const content = (
    <>
      <span className="nav-icon">{icon}</span>
      <span className="nav-label">{label}</span>
    </>
  );

  if (as === "button") {
    return (
      <button
        type="button"
        id={`nav-${id}`}
        className={className}
        onClick={onClick}
        title={label}
        aria-label={label}
      >
        {content}
      </button>
    );
  }

  return (
    <div id={`nav-${id}`} className={className} onClick={onClick} role="button" tabIndex={0}>
      {content}
    </div>
  );
}
