import type { BlockNoteEditor } from "@blocknote/core";
import { SideMenuExtension } from "@blocknote/core/extensions";
import { useEffect, useRef } from "react";

const WEBKIT_CLASS = "note-webkit-safari";
const GHOST_CLASS = "note-drag-preview";
const NOTE_ROOT = "#screen-note";

type SideMenuExtensionApi = {
  store?: { state?: { block?: { id?: string } } | undefined };
};

/** Desktop + iOS Safari (excludes Chrome/Firefox-on-iOS). */
function isWebKitSafari(): boolean {
  if (typeof navigator === "undefined") return false;
  const ua = navigator.userAgent;
  return /Safari/i.test(ua) && !/Chrome|Chromium|CriOS|Edg|OPR|OPiOS|FxiOS/i.test(ua);
}

function getSideMenuBlockId(editor: BlockNoteEditor): string | null {
  const sideMenu = editor.getExtension(SideMenuExtension) as
    | SideMenuExtensionApi
    | undefined;
  return sideMenu?.store?.state?.block?.id ?? null;
}

function findBlockOuterById(blockId: string): HTMLElement | null {
  const container = document.querySelector<HTMLElement>(
    `${NOTE_ROOT} [data-node-type="blockContainer"][data-id="${CSS.escape(blockId)}"]`,
  );
  return container?.closest<HTMLElement>(".bn-block-outer") ?? container;
}

function isNoteDragHandle(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false;
  if (!target.closest(NOTE_ROOT)) return false;
  return (
    !!target.closest('[data-test="dragHandle"]') ||
    !!target.closest(".bn-side-menu .bn-button[draggable]")
  );
}

function resolveBlockOuter(
  editor: BlockNoteEditor,
  preview: HTMLElement,
  fallbackBlockId: string | null,
): HTMLElement | null {
  const menuBlockId = getSideMenuBlockId(editor);
  if (menuBlockId) {
    const fromMenu = findBlockOuterById(menuBlockId);
    if (fromMenu) return fromMenu;
  }

  if (fallbackBlockId) {
    const fromId = findBlockOuterById(fallbackBlockId);
    if (fromId) return fromId;
  }

  const fromPreview = preview.querySelector<HTMLElement>(".bn-block-outer");
  if (fromPreview) return fromPreview;

  return preview.closest<HTMLElement>(".bn-block-outer");
}

function sanitizeGhostClone(ghost: HTMLElement): void {
  ghost.querySelectorAll("[id]").forEach((el) => el.removeAttribute("id"));
  ghost.querySelectorAll("[draggable]").forEach((el) => el.removeAttribute("draggable"));
  ghost.querySelectorAll("[contenteditable]").forEach((el) => {
    el.removeAttribute("contenteditable");
  });
  ghost.querySelectorAll("iframe, embed, object").forEach((el) => el.remove());
  ghost.querySelectorAll(".bn-side-menu").forEach((el) => el.remove());
}

function buildDragGhost(source: HTMLElement): HTMLElement {
  const ghost = source.cloneNode(true) as HTMLElement;
  ghost.classList.add(GHOST_CLASS);
  sanitizeGhostClone(ghost);

  const rect = source.getBoundingClientRect();
  ghost.style.boxSizing = "border-box";
  ghost.style.position = "fixed";
  ghost.style.left = `${rect.left}px`;
  ghost.style.top = `${rect.top}px`;
  ghost.style.width = `${rect.width}px`;
  ghost.style.pointerEvents = "none";
  ghost.style.margin = "0";
  ghost.style.zIndex = "2147483647";

  document.body.appendChild(ghost);
  void ghost.offsetHeight;

  return ghost;
}

function computeHotspot(ghost: HTMLElement, pointer: { x: number; y: number }): [number, number] {
  const gr = ghost.getBoundingClientRect();
  const w = Math.max(1, gr.width);
  const h = Math.max(1, gr.height);
  return [
    Math.max(0, Math.min(pointer.x - gr.left, w - 1)),
    Math.max(0, Math.min(pointer.y - gr.top, h - 1)),
  ];
}

function hideBlockNoteDragPreview(): void {
  document.querySelectorAll<HTMLElement>(".bn-drag-preview").forEach((el) => {
    el.style.opacity = "0.001";
    el.style.pointerEvents = "none";
  });
}

/**
 * Safari/WebKit: drag-preview ghost (draft cards pattern). Does not hide the source
 * block in the editor — that breaks BlockNote drop and leaves orphan empty lines.
 */
export function useSafariNoteEditorFixes(editor: BlockNoteEditor): void {
  const ghostRef = useRef<HTMLElement | null>(null);
  const draggingBlockIdRef = useRef<string | null>(null);
  const noteDragActiveRef = useRef(false);
  const pointerRef = useRef({ x: 0, y: 0 });

  useEffect(() => {
    if (!isWebKitSafari()) return;

    document.documentElement.classList.add(WEBKIT_CLASS);

    const clearGhost = () => {
      ghostRef.current?.remove();
      ghostRef.current = null;
      document.querySelectorAll<HTMLElement>(".bn-drag-preview").forEach((el) => {
        el.style.opacity = "";
        el.style.pointerEvents = "";
      });
    };

    const onDragStartCapture = (event: DragEvent) => {
      if (!isNoteDragHandle(event.target)) return;
      noteDragActiveRef.current = true;
      draggingBlockIdRef.current = getSideMenuBlockId(editor);
      pointerRef.current = { x: event.clientX, y: event.clientY };
    };

    const onDragEnd = () => {
      if (!noteDragActiveRef.current) return;
      noteDragActiveRef.current = false;
      draggingBlockIdRef.current = null;
      requestAnimationFrame(clearGhost);
    };

    const nativeSetDragImage = DataTransfer.prototype.setDragImage;
    DataTransfer.prototype.setDragImage = function setDragImagePatched(
      image: Element,
      xOffset: number,
      yOffset: number,
    ) {
      if (
        noteDragActiveRef.current &&
        image instanceof HTMLElement &&
        image.classList.contains("bn-drag-preview")
      ) {
        const capturedBlockId = draggingBlockIdRef.current ?? getSideMenuBlockId(editor);
        const blockOuter = resolveBlockOuter(editor, image, capturedBlockId);

        if (!(blockOuter instanceof HTMLElement)) {
          return nativeSetDragImage.call(this, image, xOffset, yOffset);
        }

        ghostRef.current?.remove();
        const ghost = buildDragGhost(blockOuter);
        const [hx, hy] = computeHotspot(ghost, pointerRef.current);

        try {
          const result = nativeSetDragImage.call(this, ghost, hx, hy);
          ghostRef.current = ghost;
          hideBlockNoteDragPreview();

          requestAnimationFrame(() => {
            requestAnimationFrame(() => {
              if (!ghostRef.current) return;
              ghostRef.current.style.left = "-9999px";
              ghostRef.current.style.top = "0";
            });
          });

          return result;
        } catch {
          ghost.remove();
          ghostRef.current = null;
          return nativeSetDragImage.call(this, image, xOffset, yOffset);
        }
      }

      return nativeSetDragImage.call(this, image, xOffset, yOffset);
    };

    document.addEventListener("dragstart", onDragStartCapture, true);
    document.addEventListener("dragend", onDragEnd, true);

    return () => {
      document.documentElement.classList.remove(WEBKIT_CLASS);
      document.removeEventListener("dragstart", onDragStartCapture, true);
      document.removeEventListener("dragend", onDragEnd, true);
      DataTransfer.prototype.setDragImage = nativeSetDragImage;
      noteDragActiveRef.current = false;
      draggingBlockIdRef.current = null;
      clearGhost();
    };
  }, [editor]);
}
