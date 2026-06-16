"use client";

import type { ReactNode } from "react";

import { ContextMenu, type CtxMenuItem } from "@/shared/ui/context-menu";

export type PageHeaderOverflowItem = {
  label: string;
  onClick?: () => void;
  icon?: ReactNode;
  danger?: boolean;
  disabled?: boolean;
  hidden?: boolean;
  active?: boolean;
};

type PageHeaderOverflowProps = {
  items: PageHeaderOverflowItem[];
  triggerAriaLabel?: string;
  className?: string;
};

export function PageHeaderOverflow({
  items,
  triggerAriaLabel = "Действия в шапке",
  className,
}: PageHeaderOverflowProps) {
  const menuItems: CtxMenuItem[] = items
    .filter((item) => !item.hidden)
    .map((item) => ({
      label: item.label,
      icon: item.icon,
      danger: item.danger,
      disabled: item.disabled,
      active: item.active,
      onClick: item.onClick,
    }));

  if (menuItems.length === 0) return null;

  return (
    <div className={className ?? undefined}>
      <ContextMenu
        className="page-header-overflow"
        dropdownClassName="ctx-dropdown--page-header-control"
        items={menuItems}
        triggerAriaLabel={triggerAriaLabel}
        portal
        align="right"
      />
    </div>
  );
}
