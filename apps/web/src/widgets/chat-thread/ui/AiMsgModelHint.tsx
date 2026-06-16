"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { BrainIcon } from "@/shared/ui/model-picker";

type Props = {
  modelTitle: string;
};

export default function AiMsgModelHint({ modelTitle }: Props) {
  const anchorRef = useRef<HTMLSpanElement>(null);
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const trimmed = modelTitle.trim();

  const syncPos = useCallback(() => {
    const el = anchorRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    setPos({ top: rect.top - 6, left: rect.left + rect.width / 2 });
  }, []);

  const show = useCallback(() => {
    if (!trimmed) return;
    syncPos();
    setOpen(true);
  }, [syncPos, trimmed]);

  const hide = useCallback(() => setOpen(false), []);

  useEffect(() => {
    if (!open) return;
    const onScroll = () => hide();
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", syncPos);
    return () => {
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", syncPos);
    };
  }, [hide, open, syncPos]);

  return (
    <>
      <span
        ref={anchorRef}
        className={`msg-ai-variant-model${trimmed ? "" : " msg-ai-variant-model--empty"}`}
        role="img"
        tabIndex={trimmed ? 0 : undefined}
        aria-label={trimmed ? `Модель: ${trimmed}` : "Модель"}
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
      >
        <span className="ai-msg-toolbar-model-ico" aria-hidden>
          <BrainIcon />
        </span>
      </span>
      {open && pos && trimmed && typeof document !== "undefined"
        ? createPortal(
            <div
              className="ctx-dropdown ctx-dropdown-portal ai-msg-model-tooltip open"
              role="tooltip"
              style={{ top: pos.top, left: pos.left }}
            >
              {trimmed}
            </div>,
            document.body,
          )
        : null}
    </>
  );
}
