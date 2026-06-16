"use client";

import { useCallback, type RefObject } from "react";
import { VIEW_EMBED_DRAG_THRESHOLD_SQ } from "@/widgets/note-editor/ui/noteBodyEditor/constants";
import type { NoteBodyEmbedDragState } from "@/widgets/note-editor/model/noteBodyEditor/useNoteBodyEmbedDragState";
import { dropBeforeToImageSlot, isImageEmbedRow, type BodyLine, type CellPos } from "@/shared/lib/noteEmbeds";
import type { NoteFile } from "@/shared/types";

type DropApi = {
  commitDropAt: (before: CellPos, embedName?: string) => void;
  updateDropTarget: (clientX: number, clientY: number) => void;
  resolveDropForCommit: (clientX: number, clientY: number) => CellPos;
};

type Params = {
  drag: NoteBodyEmbedDragState;
  filesRef: RefObject<NoteFile[]>;
  drop: DropApi;
};

export function useNoteBodyEmbedPointer({ drag, filesRef, drop }: Params) {
  const {
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
    setDragFrom,
    setDropBefore,
    setDropLineBefore,
    setImageDropSlot,
    clearDrag,
    syncDragFloatPosition,
  } = drag;

  const initEmbedDragSession = useCallback(
    (pos: CellPos, lineCtx?: BodyLine, lineIndexCtx?: number, overlayPos?: { x: number; y: number }) => {
      dragSourceRef.current = pos;
      dragFromRef.current = pos;
      dragMovedRef.current = false;
      dropLineBeforeRef.current = null;
      currentDropRef.current = { type: "before", before: { line: pos.line, cell: pos.cell } };
      committedSlotRef.current = null;
      dropCommittedRef.current = { line: pos.line, cell: pos.cell };
      setDropBefore({ line: pos.line, cell: pos.cell });
      setDropLineBefore(null);
      setDragFrom(pos);
      if (overlayPos) {
        syncDragFloatPosition(overlayPos.x, overlayPos.y);
      }

      const curFiles = filesRef.current;
      if (lineCtx != null && lineIndexCtx !== undefined && isImageEmbedRow(lineCtx, curFiles)) {
        const startSlot = dropBeforeToImageSlot(
          lineCtx,
          lineIndexCtx,
          { line: lineIndexCtx, cell: pos.cell },
          null,
        );
        imageDropSlotRef.current = { line: lineIndexCtx, slot: startSlot };
        setImageDropSlot({ line: lineIndexCtx, slot: startSlot });
      } else {
        imageDropSlotRef.current = null;
        setImageDropSlot(null);
      }
    },
    [
      committedSlotRef,
      currentDropRef,
      dragFromRef,
      dragMovedRef,
      dragSourceRef,
      dropCommittedRef,
      dropLineBeforeRef,
      filesRef,
      imageDropSlotRef,
      setDragFrom,
      setDropBefore,
      setDropLineBefore,
      setImageDropSlot,
      syncDragFloatPosition,
    ],
  );

  const runEmbedPointerDrag = useCallback(
    (
      pos: CellPos,
      lineCtx: BodyLine | undefined,
      lineIndexCtx: number | undefined,
      pointerId: number,
      clientX: number,
      clientY: number,
      captureFallbackEl: HTMLElement | null,
    ) => {
      if (pointerDragSessionRef.current) return;

      pointerDragSessionRef.current = true;
      const captureEl = typeof document !== "undefined" ? document.body : captureFallbackEl;
      pointerCaptureElRef.current = captureEl ?? captureFallbackEl;
      activePointerIdRef.current = pointerId;
      try {
        captureEl?.setPointerCapture(pointerId);
      } catch {
        try {
          if (captureFallbackEl) {
            captureFallbackEl.setPointerCapture(pointerId);
            pointerCaptureElRef.current = captureFallbackEl;
          }
        } catch {
          /* ignore */
        }
      }

      initEmbedDragSession(pos, lineCtx, lineIndexCtx, { x: clientX, y: clientY });

      const capEl = pointerCaptureElRef.current;
      if (!capEl) {
        pointerDragSessionRef.current = false;
        return;
      }
      const capTarget = capEl;
      let finished = false;

      function teardown() {
        if (finished) return;
        finished = true;
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
        window.removeEventListener("pointercancel", onUp);
        capTarget.removeEventListener("lostpointercapture", onLostCapture);
      }

      function onLostCapture(ev: PointerEvent) {
        if (ev.pointerId !== activePointerIdRef.current) return;
        teardown();
        pointerCaptureElRef.current = null;
        activePointerIdRef.current = null;
        pointerDragSessionRef.current = false;
        clearDrag();
      }

      function onMove(ev: PointerEvent) {
        if (ev.pointerId !== activePointerIdRef.current) return;
        ev.preventDefault();
        dragMovedRef.current = true;
        syncDragFloatPosition(ev.clientX, ev.clientY);
        drop.updateDropTarget(ev.clientX, ev.clientY);
      }

      function onUp(ev: PointerEvent) {
        if (ev.pointerId !== activePointerIdRef.current) return;
        teardown();

        const cap = pointerCaptureElRef.current;
        const pid = ev.pointerId;
        pointerCaptureElRef.current = null;
        activePointerIdRef.current = null;
        pointerDragSessionRef.current = false;
        try {
          cap?.releasePointerCapture(pid);
        } catch {
          /* released */
        }

        const before = drop.resolveDropForCommit(ev.clientX, ev.clientY);
        drop.commitDropAt(before);
      }

      capTarget.addEventListener("lostpointercapture", onLostCapture);
      window.addEventListener("pointermove", onMove, { passive: false });
      window.addEventListener("pointerup", onUp);
      window.addEventListener("pointercancel", onUp);
    },
    [
      activePointerIdRef,
      clearDrag,
      drop,
      dragMovedRef,
      initEmbedDragSession,
      pointerCaptureElRef,
      pointerDragSessionRef,
      syncDragFloatPosition,
    ],
  );

  const beginEmbedPointerDrag = useCallback(
    (pos: CellPos, e: React.PointerEvent, lineCtx?: BodyLine, lineIndexCtx?: number) => {
      if (pointerDragSessionRef.current) return;
      if (e.button !== 0) return;

      const fallback = e.currentTarget instanceof HTMLElement ? e.currentTarget : null;

      e.stopPropagation();
      const startX = e.clientX;
      const startY = e.clientY;
      const pid = e.pointerId;

      const onTentativeMove = (ev: PointerEvent) => {
        if (ev.pointerId !== pid) return;
        const dx = ev.clientX - startX;
        const dy = ev.clientY - startY;
        if (dx * dx + dy * dy < VIEW_EMBED_DRAG_THRESHOLD_SQ) return;
        window.removeEventListener("pointermove", onTentativeMove);
        window.removeEventListener("pointerup", onTentativeUp);
        window.removeEventListener("pointercancel", onTentativeUp);
        ev.preventDefault();
        runEmbedPointerDrag(pos, lineCtx, lineIndexCtx, pid, ev.clientX, ev.clientY, fallback);
      };

      const onTentativeUp = (ev: PointerEvent) => {
        if (ev.pointerId !== pid) return;
        window.removeEventListener("pointermove", onTentativeMove);
        window.removeEventListener("pointerup", onTentativeUp);
        window.removeEventListener("pointercancel", onTentativeUp);
      };

      window.addEventListener("pointermove", onTentativeMove, { passive: false });
      window.addEventListener("pointerup", onTentativeUp);
      window.addEventListener("pointercancel", onTentativeUp);
    },
    [pointerDragSessionRef, runEmbedPointerDrag],
  );

  return { beginEmbedPointerDrag };
}
