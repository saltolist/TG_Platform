"use client";

import { useEffect, useRef } from "react";

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
}): void {
  const { open } = options;
  const onReflowRef = useRef(options.onReflow);
  const onCloseRef = useRef(options.onClose);

  useEffect(() => {
    onReflowRef.current = options.onReflow;
    onCloseRef.current = options.onClose;
  });

  useEffect(() => {
    if (!open) return;

    const onResize = () => onReflowRef.current();
    const onScroll = isDesktopFinePointer()
      ? () => onCloseRef.current()
      : () => onReflowRef.current();

    window.addEventListener("resize", onResize);
    window.addEventListener("scroll", onScroll, true);
    return () => {
      window.removeEventListener("resize", onResize);
      window.removeEventListener("scroll", onScroll, true);
    };
  }, [open]);
}
