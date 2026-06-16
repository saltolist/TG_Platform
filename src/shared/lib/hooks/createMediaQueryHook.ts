"use client";

import { useSyncExternalStore } from "react";

/** Подписка на matchMedia + resize — корректно реагирует на постепенное сужение окна. */
export function createMediaQueryHook(query: string, serverDefault = false) {
  function subscribe(onStoreChange: () => void) {
    if (typeof window === "undefined") return () => {};
    const mq = window.matchMedia(query);
    const onChange = () => onStoreChange();
    mq.addEventListener("change", onChange);
    window.addEventListener("resize", onChange);
    return () => {
      mq.removeEventListener("change", onChange);
      window.removeEventListener("resize", onChange);
    };
  }

  function getSnapshot() {
    return window.matchMedia(query).matches;
  }

  function getServerSnapshot() {
    return serverDefault;
  }

  return function useMediaQueryHook(): boolean {
    return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  };
}
