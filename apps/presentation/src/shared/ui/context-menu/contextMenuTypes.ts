import type { ReactNode } from "react";

export type CtxMenuItem = {
  label: string;
  icon?: ReactNode;
  onClick?: () => void;
  danger?: boolean;
  active?: boolean;
  disabled?: boolean;
};

export type PortalLayout = {
  top: number;
  left: number;
  minWidth: number;
  width?: number;
  visible: boolean;
};

export type PortalLayoutOpts = {
  align: "left" | "right";
  matchTriggerWidth: boolean;
  panelMinWidth?: number;
};

export type ContextMenuProps = {
  items: CtxMenuItem[];
  trigger?: ReactNode;
  className?: string;
  dropdownClassName?: string;
  triggerVariant?: "menu" | "custom";
  triggerClassName?: string;
  panelMinWidth?: number;
  matchTriggerWidth?: boolean;
  align?: "left" | "right";
  portal?: boolean;
  onOpenChange?: (open: boolean) => void;
  triggerAriaLabel?: string;
};
