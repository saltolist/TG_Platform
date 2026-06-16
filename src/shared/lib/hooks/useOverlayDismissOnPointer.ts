"use client";

import { useCallback, useEffect, useRef, type RefObject } from "react";

import { useMobile760 } from "@/shared/lib/hooks/useMobile760";

type Options = {
  open: boolean;
  onClose: () => void;
  contentRef: RefObject<HTMLElement | null>;
  triggerRef?: RefObject<HTMLElement | null>;
  enabled?: boolean;
};

/**
 * Закрытие оверлея при касании снаружи.
 * На мобильной (≤760px) — `pointerdown` в capture: любое касание вне панели закрывает сразу.
 */
export function useOverlayDismissOnPointer({
  open,
  onClose,
  contentRef,
  triggerRef,
  enabled = true,
}: Options) {
  const isMobile = useMobile760();
  const suppressTriggerClickRef = useRef(false);
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  });

  const consumeSuppressTriggerClick = useCallback(() => {
    if (!suppressTriggerClickRef.current) return false;
    suppressTriggerClickRef.current = false;
    return true;
  }, []);

  useEffect(() => {
    if (!enabled || !open) return;

    const close = () => onCloseRef.current();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };

    if (isMobile) {
      const onPointerDown = (event: PointerEvent) => {
        const target = event.target as Node;
        if (contentRef.current?.contains(target)) return;

        close();

        if (triggerRef?.current?.contains(target)) {
          suppressTriggerClickRef.current = true;
          event.preventDefault();
          event.stopPropagation();
        }
      };

      document.addEventListener("pointerdown", onPointerDown, true);
      document.addEventListener("keydown", onKeyDown);
      return () => {
        document.removeEventListener("pointerdown", onPointerDown, true);
        document.removeEventListener("keydown", onKeyDown);
      };
    }

    const onMouseDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (triggerRef?.current?.contains(target)) return;
      if (contentRef.current?.contains(target)) return;
      close();
    };

    document.addEventListener("mousedown", onMouseDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onMouseDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [enabled, open, isMobile, contentRef, triggerRef]);

  return { isMobile, consumeSuppressTriggerClick };
}
