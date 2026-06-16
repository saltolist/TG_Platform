"use client";

import { useSyncExternalStore } from "react";

function createPageHeaderBreakpointHook(attr: string) {
  function subscribe(onStoreChange: () => void) {
    const observer = new MutationObserver(onStoreChange);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: [attr],
    });
    return () => observer.disconnect();
  }

  function getSnapshot() {
    return document.documentElement.hasAttribute(attr);
  }

  function getServerSnapshot() {
    return false;
  }

  return function usePageHeaderBreakpoint(): boolean {
    return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  };
}

/** Ширина `.page-header` ≤ 640px — графики с ≤10 точками (desktop/tablet, не mobile). */
export const usePageHeaderLe640 = createPageHeaderBreakpointHook("data-page-header-le-640");

/** Ширина `.page-header` ≤ 650px — период аналитики платформы в шапке (desktop/tablet). */
export const usePageHeaderLe650 = createPageHeaderBreakpointHook("data-page-header-le-650");

/** Ширина `.page-header` ≤ 780px (см. PROFILE_HEADER_TOP_POSTS_COMPACT_MAX). */
export const usePageHeaderLe780 = createPageHeaderBreakpointHook("data-page-header-le-780");

/** Ширина `.page-header` ≤ 1080px — графики с ≤15 точками (desktop/tablet, не mobile). */
export const usePageHeaderLe1080 = createPageHeaderBreakpointHook("data-page-header-le-1080");
