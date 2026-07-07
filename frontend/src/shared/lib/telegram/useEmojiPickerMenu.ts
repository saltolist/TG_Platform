"use client";

import { useCallback, useLayoutEffect, useRef, useState } from "react";

import { useFloatingPanelScrollListeners } from "@/shared/lib/hooks/useFloatingPanelScrollListeners";
import { useOverlayDismissOnPointer } from "@/shared/lib/hooks/useOverlayDismissOnPointer";

type Pos =
  | { mode: "up"; bottom: number; left: number }
  | { mode: "down"; top: number; left: number };

const MENU_WIDTH_ESTIMATE = 280;
const MENU_GAP = 6;

type Options = {
  placement?: "up" | "down" | "down-right";
  disabled?: boolean;
};

export function useEmojiPickerMenu({ placement = "up", disabled = false }: Options = {}) {
  const [open, setOpen] = useState(false);
  const [collectionIndex, setCollectionIndex] = useState(0);
  const [pos, setPos] = useState<Pos | null>(null);

  const wrapRef = useRef<HTMLDivElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const updatePos = useCallback(() => {
    const btn = btnRef.current;
    if (!btn) return;
    const r = btn.getBoundingClientRect();

    if (placement === "down" || placement === "down-right") {
      let left = placement === "down-right" ? r.right + MENU_GAP : r.left;
      const maxLeft = window.innerWidth - MENU_WIDTH_ESTIMATE - 8;
      left = Math.min(Math.max(8, left), maxLeft);
      setPos({ mode: "down", top: r.bottom + MENU_GAP, left });
      return;
    }

    setPos({ mode: "up", bottom: window.innerHeight - r.top + MENU_GAP, left: r.left });
  }, [placement]);

  useLayoutEffect(() => {
    if (open) updatePos();
  }, [open, updatePos]);

  const closeMenu = useCallback(() => {
    setOpen(false);
  }, []);

  const { consumeSuppressTriggerClick } = useOverlayDismissOnPointer({
    open,
    onClose: closeMenu,
    contentRef: menuRef,
    triggerRef: btnRef,
  });

  useFloatingPanelScrollListeners({
    open,
    onReflow: updatePos,
    onClose: closeMenu,
    ignoreScrollWithinRef: menuRef,
  });

  const onTriggerClick = useCallback(
    (event: React.MouseEvent) => {
      event.stopPropagation();
      if (disabled || consumeSuppressTriggerClick()) return;
      setOpen((value) => {
        const next = !value;
        if (next) {
          setCollectionIndex(0);
        }
        return next;
      });
    },
    [consumeSuppressTriggerClick, disabled],
  );

  return {
    open,
    pos,
    wrapRef,
    btnRef,
    menuRef,
    collectionIndex,
    setCollectionIndex,
    onTriggerClick,
    closeMenu,
  };
}
