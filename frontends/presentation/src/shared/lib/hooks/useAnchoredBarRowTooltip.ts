"use client";

import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";

/** Мобильный тултип: открытие по тапу/клику, закрытие повторным тапом или тапом вне строки. */
export function useAnchoredBarRowTooltip(isMobile: boolean) {
  const rowRef = useRef<HTMLTableRowElement | HTMLDivElement>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!isMobile || !open) return;

    const closeIfOutside = (event: PointerEvent) => {
      const row = rowRef.current;
      if (row && !row.contains(event.target as Node)) {
        setOpen(false);
      }
    };

    document.addEventListener("pointerdown", closeIfOutside, true);
    return () => document.removeEventListener("pointerdown", closeIfOutside, true);
  }, [isMobile, open]);

  const toggleOpen = useCallback(() => {
    setOpen((prev) => !prev);
  }, []);

  const mobileHandlers = isMobile
    ? {
        onClick: (event: { stopPropagation: () => void }) => {
          event.stopPropagation();
          toggleOpen();
        },
        onKeyDown: (event: KeyboardEvent<HTMLElement>) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            toggleOpen();
          }
          if (event.key === "Escape") {
            setOpen(false);
          }
        },
      }
    : {};

  return { rowRef, open, mobileHandlers };
}
