"use client";

import { MenuIconPlus } from "@/shared/ui/icons/header-menu-icons";
import { cn } from "@/shared/lib/utils";
import { PageHeaderControl } from "@/shared/ui/page-header-tab-group";

type Props = {
  label: string;
  onClick: () => void;
  className?: string;
  iconClassName?: string;
};

export default function FilterToolbarAction({
  label,
  onClick,
  className = "",
  iconClassName = "filter-toolbar-action-icon",
}: Props) {
  return (
    <PageHeaderControl
      active
      className={cn("filter-toolbar-action", className)}
      onClick={onClick}
    >
      <span className={iconClassName} aria-hidden>
        <MenuIconPlus size={12} strokeWidth={2} />
      </span>
      <span>{label}</span>
    </PageHeaderControl>
  );
}
