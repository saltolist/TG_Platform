"use client";

import { useMemo } from "react";

import { ContextMenu } from "@/shared/ui/context-menu";

type Props = {
  showDeleted: boolean;
  onShowDeletedChange: (value: boolean) => void;
};

export function FeedHeaderMenu({ showDeleted, onShowDeletedChange }: Props) {
  const items = useMemo(
    () => [
      {
        kind: "checkbox" as const,
        label: "Показать удалённые",
        checked: showDeleted,
        keepOpen: true,
        onClick: () => onShowDeletedChange(!showDeleted),
      },
    ],
    [onShowDeletedChange, showDeleted],
  );

  return (
    <ContextMenu
      items={items}
      portal
      align="right"
      dropdownClassName="ctx-dropdown--page-header-control"
      triggerAriaLabel="Настройки ленты"
    />
  );
}
