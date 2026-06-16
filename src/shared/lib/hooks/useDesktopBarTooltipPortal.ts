"use client";

import { useState, type FocusEvent, type MouseEvent } from "react";
import { useFloatingPanelScrollListeners } from "@/shared/lib/hooks/useFloatingPanelScrollListeners";

export type DesktopTooltipPos = { x: number; y: number };

/** Портальный тултип у полосы метрик: на desktop закрывается при скролле (без дёрганья). */
export function useDesktopBarTooltipPortal(desktop: boolean) {
  const [desktopTooltipPos, setDesktopTooltipPos] = useState<DesktopTooltipPos | null>(null);

  useFloatingPanelScrollListeners({
    open: desktop && desktopTooltipPos !== null,
    onReflow: () => {},
    onClose: () => setDesktopTooltipPos(null),
  });

  const desktopTooltipHandlers = desktop
    ? {
        onMouseEnter: (event: MouseEvent<HTMLElement>) => {
          const rect = event.currentTarget.getBoundingClientRect();
          setDesktopTooltipPos({ x: event.clientX, y: rect.top });
        },
        onMouseMove: (event: MouseEvent<HTMLElement>) => {
          const rect = event.currentTarget.getBoundingClientRect();
          setDesktopTooltipPos({ x: event.clientX, y: rect.top });
        },
        onMouseLeave: () => setDesktopTooltipPos(null),
        onFocus: (event: FocusEvent<HTMLElement>) => {
          const rect = event.currentTarget.getBoundingClientRect();
          setDesktopTooltipPos({ x: rect.left + rect.width / 2, y: rect.top });
        },
        onBlur: () => setDesktopTooltipPos(null),
      }
    : {};

  return { desktopTooltipPos, desktopTooltipHandlers };
}
