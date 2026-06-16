import { useEffect, type RefObject } from "react";
import { lockViewportZoom, unlockViewportZoom } from "@/shared/lib/viewportZoomLock";

/**
 * На iOS Safari поля с font-size < 16px вызывают zoom при фокусе.
 * Блокируем через maximum-scale=1 до focus (touchstart), без смены шрифта.
 */
export function usePreventIosInputZoom(
  ref: RefObject<HTMLElement | null>,
  enabled: boolean,
) {
  useEffect(() => {
    if (!enabled) return;
    const el = ref.current;
    if (!el) return;

    let armedFromTouch = false;

    const onTouchStart = () => {
      lockViewportZoom();
      armedFromTouch = true;
    };
    const onFocus = () => {
      if (!armedFromTouch) lockViewportZoom();
      armedFromTouch = false;
    };
    const onBlur = () => {
      armedFromTouch = false;
      unlockViewportZoom();
    };

    el.addEventListener("touchstart", onTouchStart, { passive: true });
    el.addEventListener("focus", onFocus);
    el.addEventListener("blur", onBlur);

    return () => {
      el.removeEventListener("touchstart", onTouchStart);
      el.removeEventListener("focus", onFocus);
      el.removeEventListener("blur", onBlur);
      unlockViewportZoom();
    };
  }, [ref, enabled]);
}
