"use client";

import { SidebarRecentRow, type SidebarRecentRowItem } from "@/widgets/sidebar/ui/sidebar-recent-row";

type SidebarRecentListProps = {
  items: SidebarRecentRowItem[];
  grouped?: {
    thisPost: SidebarRecentRowItem[];
    others: SidebarRecentRowItem[];
  };
  emptyLabel: string;
};

export function SidebarRecentList({ items, grouped, emptyLabel }: SidebarRecentListProps) {
  if (grouped) {
    return (
      <div className="nav-recent-chats">
        <div className="nav-recent-chats-section-label">Этот пост</div>
        {grouped.thisPost.length === 0 ? (
          <div className="nav-recent-empty">{emptyLabel}</div>
        ) : (
          grouped.thisPost.map((item) => <SidebarRecentRow key={item.key} item={item} />)
        )}
        <div className="nav-recent-chats-section-label">Остальные</div>
        {grouped.others.length === 0 ? (
          <div className="nav-recent-empty">{emptyLabel}</div>
        ) : (
          grouped.others.map((item) => <SidebarRecentRow key={item.key} item={item} />)
        )}
      </div>
    );
  }

  if (items.length === 0) return null;

  return (
    <div className="nav-recent-chats">
      {items.map((item) => (
        <SidebarRecentRow key={item.key} item={item} />
      ))}
    </div>
  );
}
