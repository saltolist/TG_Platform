"use client";

import BrandStarIcon from "@/widgets/sidebar/ui/BrandStarIcon";
import RailPanelToggleIcon from "@/widgets/sidebar/ui/RailPanelToggleIcon";

type SidebarHeaderProps = {
  railActive: boolean;
  railAllowed: boolean;
  onGoHome: () => void;
  onExpand: () => void;
  onCollapse: () => void;
};

export function SidebarHeader({
  railActive,
  railAllowed,
  onGoHome,
  onExpand,
  onCollapse,
}: SidebarHeaderProps) {
  return (
    <div className="sidebar-header">
      {railAllowed ? (
        railActive ? (
          <button
            type="button"
            className="sidebar-brand-mark-hit"
            onClick={onExpand}
            aria-pressed
            aria-label="Развернуть панель"
            title="Развернуть панель"
          >
            <span className="sidebar-brand-mark-layer sidebar-brand-mark-layer--logo">
              <span className="sidebar-brand-mark" aria-hidden>
                <BrandStarIcon />
              </span>
            </span>
            <span className="sidebar-brand-mark-layer sidebar-brand-mark-layer--toggle" aria-hidden>
              <RailPanelToggleIcon />
            </span>
          </button>
        ) : (
          <div className="sidebar-brand-split">
            <button
              type="button"
              className="sidebar-brand"
              onClick={onGoHome}
              title="TG Platform"
              aria-label="TG Platform — на главную"
            >
              <span className="sidebar-brand-mark" aria-hidden>
                <BrandStarIcon />
              </span>
              <span className="sidebar-brand-name">TG Platform</span>
            </button>
            <button
              type="button"
              className="sidebar-collapse-btn"
              onClick={onCollapse}
              aria-label="Свернуть панель"
              title="Свернуть панель"
            >
              <span className="sidebar-collapse-btn-inner" aria-hidden>
                <RailPanelToggleIcon />
              </span>
            </button>
          </div>
        )
      ) : (
        <button
          type="button"
          className="sidebar-brand"
          onClick={onGoHome}
          title="TG Platform"
          aria-label="TG Platform — на главную"
        >
          <span className="sidebar-brand-mark" aria-hidden>
            <BrandStarIcon />
          </span>
          <span className="sidebar-brand-name">TG Platform</span>
        </button>
      )}
    </div>
  );
}
