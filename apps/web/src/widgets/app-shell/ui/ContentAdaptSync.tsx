"use client";

import { useLayoutEffect } from "react";

import { syncContentAdaptWidthToDocument } from "@/shared/lib/contentAdaptWidth";
import { clearProfileAdaptFromDocument } from "@/shared/lib/profileBreakpoints";

/** Синхронизирует --content-adapt-w и data-* для CSS-правил адаптации контента. */
export function ContentAdaptSync() {
  useLayoutEffect(() => {
    const update = () => {
      syncContentAdaptWidthToDocument();
    };
    update();
    window.addEventListener("resize", update);
    const mq = window.matchMedia("(max-width: 760px)");
    mq.addEventListener("change", update);
    return () => {
      window.removeEventListener("resize", update);
      mq.removeEventListener("change", update);
      document.documentElement.style.removeProperty("--content-adapt-w");
      document.documentElement.removeAttribute("data-content-adapt-ge-761");
      document.documentElement.removeAttribute("data-content-adapt-le-1000");
      document.documentElement.removeAttribute("data-shell-overlay");
      clearProfileAdaptFromDocument();
    };
  }, []);

  return null;
}
