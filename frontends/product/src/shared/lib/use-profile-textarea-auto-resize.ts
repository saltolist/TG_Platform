import { useCallback, useLayoutEffect, useRef } from "react";

export const PROFILE_TEXTAREA_MIN_HEIGHT_PX = 125;

export function useProfileTextareaAutoResize(
  value: string,
  active = true,
  minHeightPx = PROFILE_TEXTAREA_MIN_HEIGHT_PX,
) {
  const ref = useRef<HTMLTextAreaElement>(null);

  const resize = useCallback(() => {
    const textarea = ref.current;
    if (!textarea) return;
    textarea.style.height = "0px";
    textarea.style.overflowY = "hidden";
    textarea.style.height = `${Math.max(minHeightPx, textarea.scrollHeight)}px`;
  }, [minHeightPx]);

  useLayoutEffect(() => {
    if (!active) return;
    resize();
    const frame = requestAnimationFrame(resize);
    return () => cancelAnimationFrame(frame);
  }, [value, resize, active]);

  return { ref, resize };
}
