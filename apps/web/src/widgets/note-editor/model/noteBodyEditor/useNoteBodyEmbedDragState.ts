"use client";

import { useCallback, useRef, useState } from "react";
import type { CurrentDropTarget, ImageDropSlot } from "@/widgets/note-editor/ui/noteBodyEditor/types";
import type { CellPos } from "@/shared/lib/noteEmbeds";

export function useNoteBodyEmbedDragState() {
  const dragFromRef = useRef<CellPos | null>(null);
  const dragSourceRef = useRef<CellPos | null>(null);
  const imageDropSlotRef = useRef<ImageDropSlot | null>(null);
  const dropLineBeforeRef = useRef<number | null>(null);
  const currentDropRef = useRef<CurrentDropTarget | null>(null);
  const committedSlotRef = useRef<number | null>(null);
  const dropCommittedRef = useRef<CellPos | null>(null);
  const pointerDragSessionRef = useRef(false);
  const pointerCaptureElRef = useRef<HTMLElement | null>(null);
  const activePointerIdRef = useRef<number | null>(null);
  const dragMovedRef = useRef(false);
  const dragFloatRef = useRef<HTMLDivElement | null>(null);
  const dragFloatPosRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 });

  const [dragFrom, setDragFrom] = useState<CellPos | null>(null);
  const [dropBefore, setDropBefore] = useState<CellPos | null>(null);
  const [imageDropSlot, setImageDropSlot] = useState<ImageDropSlot | null>(null);
  const [dropLineBefore, setDropLineBefore] = useState<number | null>(null);

  const syncDragFloatPosition = useCallback((x: number, y: number) => {
    dragFloatPosRef.current = { x, y };
    const el = dragFloatRef.current;
    if (el) {
      el.style.left = `${x}px`;
      el.style.top = `${y}px`;
    }
  }, []);

  const dragFloatMountRef = useCallback((el: HTMLDivElement | null) => {
    dragFloatRef.current = el;
    if (el) {
      const p = dragFloatPosRef.current;
      el.style.left = `${p.x}px`;
      el.style.top = `${p.y}px`;
    }
  }, []);

  const clearDrag = useCallback(() => {
    dragFromRef.current = null;
    dragSourceRef.current = null;
    imageDropSlotRef.current = null;
    dropLineBeforeRef.current = null;
    currentDropRef.current = null;
    committedSlotRef.current = null;
    dropCommittedRef.current = null;
    setDragFrom(null);
    setDropBefore(null);
    setImageDropSlot(null);
    setDropLineBefore(null);
    pointerDragSessionRef.current = false;
    pointerCaptureElRef.current = null;
    activePointerIdRef.current = null;
    dragMovedRef.current = false;
  }, []);

  const setImageSlot = useCallback((line: number, slot: number) => {
    const prev = imageDropSlotRef.current;
    if (dropLineBeforeRef.current != null) {
      dropLineBeforeRef.current = null;
      setDropLineBefore(null);
    }
    if (prev?.line === line && prev?.slot === slot) return;
    imageDropSlotRef.current = { line, slot };
    setImageDropSlot({ line, slot });
  }, []);

  return {
    dragFromRef,
    dragSourceRef,
    imageDropSlotRef,
    dropLineBeforeRef,
    currentDropRef,
    committedSlotRef,
    dropCommittedRef,
    pointerDragSessionRef,
    pointerCaptureElRef,
    activePointerIdRef,
    dragMovedRef,
    dragFloatPosRef,
    dragFrom,
    setDragFrom,
    dropBefore,
    setDropBefore,
    imageDropSlot,
    setImageDropSlot,
    dropLineBefore,
    setDropLineBefore,
    clearDrag,
    setImageSlot,
    syncDragFloatPosition,
    dragFloatMountRef,
  };
}

export type NoteBodyEmbedDragState = ReturnType<typeof useNoteBodyEmbedDragState>;
