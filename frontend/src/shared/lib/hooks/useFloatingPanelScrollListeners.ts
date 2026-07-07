"use client";

import { useEffect, useRef } from "react";
import type { RefObject } from "react";

/** Мышь / трекпад: закрываем портал при скролле вместо reposition (без дёрганья). */
export function isDesktopFinePointer(): boolean {
  if (typeof window === "undefined") return false;
  return window.matchMedia("(hover: hover) and (pointer: fine)").matches;
}

/**
 * resize → onReflow; scroll на touch — onReflow; на desktop — onClose.
 */
export function useFloatingPanelScrollListeners(options: {
  open: boolean;
  onReflow: () => void;
  onClose: () => void;
  ignoreScrollWithinRef?: RefObject<HTMLElement | null>;
}): void {
  const { open } = options;
  const onReflowRef = useRef(options.onReflow);
  const onCloseRef = useRef(options.onClose);
  const ignoreScrollWithinRef = options.ignoreScrollWithinRef;

  useEffect(() => {
    onReflowRef.current = options.onReflow;
    onCloseRef.current = options.onClose;
  });

  useEffect(() => {
    if (!open) return;

    const onResize = () => onReflowRef.current();
    const onScroll = (event: Event) => {
      const ignoreRoot = ignoreScrollWithinRef?.current;
      if (ignoreRoot && event.target instanceof Node && ignoreRoot.contains(event.target)) {
        return;
      }

      if (isDesktopFinePointer()) {
        onCloseRef.current();
      } else {
        onReflowRef.current();
      }
    };

    window.addEventListener("resize", onResize);
    window.addEventListener("scroll", onScroll, true);
    return () => {
      window.removeEventListener("resize", onResize);
      window.removeEventListener("scroll", onScroll, true);
    };
  }, [open]);
}
