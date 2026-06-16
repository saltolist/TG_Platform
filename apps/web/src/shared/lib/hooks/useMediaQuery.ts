"use client";

import { useSyncExternalStore } from "react";

export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onStoreChange) => {
      if (typeof window === "undefined") return () => {};
      const mq = window.matchMedia(query);
      const onChange = () => onStoreChange();
      mq.addEventListener("change", onChange);
      window.addEventListener("resize", onChange);
      return () => {
        mq.removeEventListener("change", onChange);
        window.removeEventListener("resize", onChange);
      };
    },
    () => window.matchMedia(query).matches,
    () => false,
  );
}

export const MOBILE_MAX_MQ = "(max-width: 760px)";
export const RAIL_MIN_MQ = "(min-width: 761px)";
