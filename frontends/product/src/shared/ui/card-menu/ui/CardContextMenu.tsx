"use client";

import { ContextMenu, type CtxMenuItem } from "@/shared/ui/context-menu";
import MoreDotsIcon from "@/shared/ui/icons/more-dots";

type Props = {
  items: CtxMenuItem[];
  ariaLabel: string;
  className?: string;
};

export default function CardContextMenu({ items, ariaLabel, className = "chat-card-ctx" }: Props) {
  return (
    <ContextMenu
      className={className}
      align="right"
      portal
      triggerAriaLabel={ariaLabel}
      trigger={<MoreDotsIcon />}
      items={items}
    />
  );
}
