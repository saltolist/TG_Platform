"use client";

import { useEffect, useRef } from "react";

/**
 * Прокрутка треда вниз при новых сообщениях.
 * Переключение ветки (`historyRevision`) не трогает scrollTop.
 */
export function useChatThreadAutoScroll(
  containerRef: React.RefObject<HTMLDivElement | null>,
  messageCount: number,
  historyRevision: string,
  enabled = true,
) {
  const prevCountRef = useRef(0);
  const prevRevisionRef = useRef<string | null>(null);

  useEffect(() => {
    if (!enabled) return;
    const el = containerRef.current;
    if (!el) return;

    const countIncreased = messageCount > prevCountRef.current;
    const branchSwitched =
      prevRevisionRef.current !== null && historyRevision !== prevRevisionRef.current;

    prevCountRef.current = messageCount;
    prevRevisionRef.current = historyRevision;

    if (branchSwitched) return;

    if (countIncreased) {
      el.scrollTop = el.scrollHeight;
    }
  }, [containerRef, messageCount, historyRevision, enabled]);
}
