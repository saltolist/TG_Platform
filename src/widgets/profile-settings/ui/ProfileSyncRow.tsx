"use client";

import { useLayoutEffect, useRef, type ReactNode } from "react";
import { PROFILE_TEXTAREA_MIN_HEIGHT_PX } from "@/shared/lib/use-profile-textarea-auto-resize";

function syncProfileRowTextareas(row: HTMLElement) {
  const textareas = Array.from(
    row.querySelectorAll<HTMLTextAreaElement>("textarea.profile-textarea-compact"),
  );
  if (textareas.length === 0) return;

  textareas.forEach((textarea) => {
    textarea.style.height = "0px";
    textarea.style.overflowY = "hidden";
  });

  const maxHeight = Math.max(
    PROFILE_TEXTAREA_MIN_HEIGHT_PX,
    ...textareas.map((textarea) => textarea.scrollHeight),
  );

  textareas.forEach((textarea) => {
    textarea.style.height = `${maxHeight}px`;
    textarea.style.overflowY = "hidden";
  });
}

export default function ProfileSyncRow({
  children,
  syncKey = "",
  active = true,
}: {
  children: ReactNode;
  syncKey?: string;
  active?: boolean;
}) {
  const rowRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    if (!active) return;

    const row = rowRef.current;
    if (!row) return;

    const sync = () => syncProfileRowTextareas(row);

    sync();
    const frame = requestAnimationFrame(sync);
    row.addEventListener("input", sync);

    const resizeObserver = new ResizeObserver(sync);
    const textareas = row.querySelectorAll<HTMLTextAreaElement>("textarea.profile-textarea-compact");
    textareas.forEach((textarea) => resizeObserver.observe(textarea));

    return () => {
      cancelAnimationFrame(frame);
      row.removeEventListener("input", sync);
      resizeObserver.disconnect();
    };
  }, [syncKey, active]);

  return (
    <div className="profile-sync-row" ref={rowRef} style={{ display: "contents" }}>
      {children}
    </div>
  );
}
