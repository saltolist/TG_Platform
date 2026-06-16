import { useLayoutEffect, type RefObject } from "react";

const MAX_SIZE = 28;
const MIN_SIZE = 13;

export function useFitTitleSize(
  ref: RefObject<HTMLElement | HTMLTextAreaElement | null>,
  value: string,
  isEditing: boolean,
  options?: { maxSize?: number; minSize?: number },
) {
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;

    const maxSize = options?.maxSize ?? MAX_SIZE;
    const minSize = options?.minSize ?? MIN_SIZE;
    const isTextarea = el instanceof HTMLTextAreaElement;
    const fit = () => {
      const available = el.clientWidth;
      if (available <= 0) return;
      let size = maxSize;
      el.style.fontSize = `${size}px`;
      el.style.whiteSpace = "nowrap";
      if (isTextarea) el.setAttribute("wrap", "off");
      while (size > minSize && el.scrollWidth > available) {
        size -= 1;
        el.style.fontSize = `${size}px`;
      }
      const fitsSingleLine = el.scrollWidth <= available;
      el.classList.remove("title-single-line", "title-multi-line");
      el.classList.add(fitsSingleLine ? "title-single-line" : "title-multi-line");
      if (isTextarea) {
        const ta = el as HTMLTextAreaElement;
        ta.setAttribute("wrap", fitsSingleLine ? "off" : "soft");
        ta.style.whiteSpace = fitsSingleLine ? "nowrap" : "pre-wrap";
        ta.style.overflowX = "hidden";
        if (fitsSingleLine) {
          ta.style.height = "34px";
        } else {
          ta.style.height = "auto";
          ta.style.height = `${Math.max(ta.scrollHeight, 35)}px`;
        }
      } else {
        el.style.whiteSpace = fitsSingleLine ? "nowrap" : "normal";
      }
    };

    fit();
    requestAnimationFrame(fit);

    const onResize = () => fit();
    window.addEventListener("resize", onResize);

    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(fit) : null;
    if (observer && el.parentElement) observer.observe(el.parentElement);

    return () => {
      window.removeEventListener("resize", onResize);
      observer?.disconnect();
    };
  }, [ref, value, isEditing, options?.maxSize, options?.minSize]);
}
