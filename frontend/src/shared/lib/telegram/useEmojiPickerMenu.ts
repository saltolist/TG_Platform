"use client";

import { useCallback, useLayoutEffect, useRef, useState } from "react";

import { useFloatingPanelScrollListeners } from "@/shared/lib/hooks/useFloatingPanelScrollListeners";
import { useOverlayDismissOnPointer } from "@/shared/lib/hooks/useOverlayDismissOnPointer";

type Pos =
  | { mode: "up"; bottom: number; left: number }
  | { mode: "down"; top: number; left: number };

type Options = {
  placement?: "up" | "down";
  disabled?: boolean;
};

export function useEmojiPickerMenu({ placement = "up", disabled = false }: Options = {}) {
  const [open, setOpen] = useState(false);
  const [collectionIndex, setCollectionIndex] = useState(0);
  const [itemPage, setItemPage] = useState(0);
  const [pos, setPos] = useState<Pos | null>(null);

  const wrapRef = useRef<HTMLDivElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const updatePos = useCallback(() => {
    const btn = btnRef.current;
    if (!btn) return;
    const r = btn.getBoundingClientRect();
    if (placement === "down") {
      setPos({ mode: "down", top: r.bottom + 6, left: r.left });
    } else {
      setPos({ mode: "up", bottom: window.innerHeight - r.top + 6, left: r.left });
    }
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
  });

  const onTriggerClick = useCallback(
    (event: React.MouseEvent) => {
      event.stopPropagation();
      if (disabled || consumeSuppressTriggerClick()) return;
      setOpen((value) => {
        const next = !value;
        if (next) {
          setCollectionIndex(0);
          setItemPage(0);
        }
        return next;
      });
    },
    [consumeSuppressTriggerClick, disabled],
  );

  const resetItemPage = useCallback(() => {
    setItemPage(0);
  }, []);

  return {
    open,
    pos,
    wrapRef,
    btnRef,
    menuRef,
    collectionIndex,
    setCollectionIndex,
    itemPage,
    setItemPage,
    resetItemPage,
    onTriggerClick,
    closeMenu,
  };
}
