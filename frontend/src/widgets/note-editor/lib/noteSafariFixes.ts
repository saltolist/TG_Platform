import type { BlockNoteEditor } from "@blocknote/core";
import { SideMenuExtension } from "@blocknote/core/extensions";
import { useEffect } from "react";

const WEBKIT_CLASS = "note-webkit-safari";
const GHOST_CLASS = "note-safari-drag-ghost";
const GHOST_CAPTURED_CLASS = "note-safari-drag-ghost--captured";
const BODY_DRAG_CLASS = "note-safari-block-dragging";
const NOTE_ROOT = "#screen-note";

type SideMenuExtensionApi = {
  store?: { state?: { block?: { id?: string } } | undefined };
};

type SafariDragSession = {
  ghost: HTMLElement | null;
  pointer: { x: number; y: number };
  blockOuter: HTMLElement | null;
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

function sanitizeGhostClone(ghost: HTMLElement): void {
  ghost.removeAttribute("data-safari-drag-source");
  ghost.querySelectorAll("[data-safari-drag-source]").forEach((el) => {
    el.removeAttribute("data-safari-drag-source");
  });
  ghost.querySelectorAll("[id]").forEach((el) => el.removeAttribute("id"));
  ghost.querySelectorAll("[draggable]").forEach((el) => el.removeAttribute("draggable"));
  ghost.querySelectorAll("[contenteditable]").forEach((el) => {
    el.removeAttribute("contenteditable");
  });
  ghost.querySelectorAll("iframe, embed, object").forEach((el) => el.remove());
  ghost.querySelectorAll(".bn-side-menu").forEach((el) => el.remove());
}

/** Text-only clone: block content without chrome, background, or side menu. */
function buildTextDragGhost(blockOuter: HTMLElement): HTMLElement {
  const content =
    blockOuter.querySelector<HTMLElement>(".bn-block-content") ?? blockOuter;

  const ghost = content.cloneNode(true) as HTMLElement;
  ghost.classList.add(GHOST_CLASS);
  sanitizeGhostClone(ghost);

  const rect = content.getBoundingClientRect();
  ghost.style.boxSizing = "border-box";
  ghost.style.position = "fixed";
  ghost.style.left = `${rect.left}px`;
  ghost.style.top = `${rect.top}px`;
  ghost.style.width = `${rect.width}px`;
  ghost.style.maxWidth = "min(90vw, 100%)";
  ghost.style.margin = "0";
  ghost.style.padding = "0";
  ghost.style.pointerEvents = "none";
  ghost.style.zIndex = "2147483647";

  document.body.appendChild(ghost);
  void ghost.offsetHeight;

  return ghost;
}

function refineHotspotFromGhost(ghost: HTMLElement, pointer: { x: number; y: number }): [number, number] {
  const gr = ghost.getBoundingClientRect();
  const w = Math.max(1, gr.width);
  const h = Math.max(1, gr.height);
  const hx = Math.max(0, Math.min(pointer.x - gr.left, w - 1));
  const hy = Math.max(0, Math.min(pointer.y - gr.top, h - 1));
  return [hx, hy];
}

let activeSession: SafariDragSession | null = null;
let activeEditor: BlockNoteEditor | null = null;

function resolveDragBlockOuter(editor: BlockNoteEditor | null): HTMLElement | null {
  if (!editor) return null;
  const blockId = getSideMenuBlockId(editor);
  return blockId ? findBlockOuterById(blockId) : null;
}

function suppressSourceBlock(blockOuter: HTMLElement | null): void {
  blockOuter?.setAttribute("data-safari-drag-source", "true");
  document.body.classList.add(BODY_DRAG_CLASS);
}

function hideBlockNoteDragPreview(): void {
  document.querySelectorAll<HTMLElement>(".bn-drag-preview").forEach((el) => {
    el.style.display = "none";
    el.style.pointerEvents = "none";
  });
}

function demoteGhostAfterCapture(ghost: HTMLElement): void {
  // Opacity 0 kills WebKit drag bitmap; 0.001 hides the on-page clone only.
  ghost.classList.add(GHOST_CAPTURED_CLASS);
  ghost.style.left = "-9999px";
  ghost.style.top = "0";
}

function clearSafariDragSession(): void {
  activeSession?.ghost?.remove();
  activeSession = null;
  document.body.classList.remove(BODY_DRAG_CLASS);
  document.querySelectorAll<HTMLElement>(".bn-drag-preview").forEach((el) => {
    el.style.display = "";
    el.style.pointerEvents = "";
  });
}

/**
 * Safari/WebKit: substitute a visible text clone for BlockNote's hidden .bn-drag-preview.
 * BlockNote's native setDragImage breaks inside scroll/overflow layouts on WebKit.
 */
export function useSafariNoteEditorFixes(editor: BlockNoteEditor): void {
  useEffect(() => {
    if (!isWebKitSafari()) return;

    activeEditor = editor;
    document.documentElement.classList.add(WEBKIT_CLASS);

    const onDragStartCapture = (event: DragEvent) => {
      if (!isNoteDragHandle(event.target)) return;
      const blockOuter = resolveDragBlockOuter(activeEditor);
      // Hide source before setDragImage; ghost clone strips data-safari-drag-source.
      suppressSourceBlock(blockOuter);
      activeSession = {
        ghost: null,
        pointer: { x: event.clientX, y: event.clientY },
        blockOuter,
      };
    };

    const onDragEnd = () => {
      document
        .querySelectorAll<HTMLElement>("[data-safari-drag-source]")
        .forEach((el) => el.removeAttribute("data-safari-drag-source"));
      clearSafariDragSession();
    };

    const nativeSetDragImage = DataTransfer.prototype.setDragImage;
    DataTransfer.prototype.setDragImage = function setDragImagePatched(
      image: Element,
      xOffset: number,
      yOffset: number,
    ) {
      const session = activeSession;
      if (
        session &&
        image instanceof HTMLElement &&
        image.classList.contains("bn-drag-preview")
      ) {
        const blockOuter =
          resolveDragBlockOuter(activeEditor) ??
          session.blockOuter ??
          image.querySelector<HTMLElement>(".bn-block-outer") ??
          image.closest<HTMLElement>(".bn-block-outer");

        if (!(blockOuter instanceof HTMLElement)) {
          return nativeSetDragImage.call(this, image, xOffset, yOffset);
        }

        session.ghost?.remove();
        const ghost = buildTextDragGhost(blockOuter);
        session.ghost = ghost;

        const [hotspotX, hotspotY] = refineHotspotFromGhost(ghost, session.pointer);
        const result = nativeSetDragImage.call(this, ghost, hotspotX, hotspotY);

        hideBlockNoteDragPreview();
        demoteGhostAfterCapture(ghost);

        return result;
      }

      return nativeSetDragImage.call(this, image, xOffset, yOffset);
    };

    document.addEventListener("dragstart", onDragStartCapture, true);
    document.addEventListener("dragend", onDragEnd, true);
    document.addEventListener("drop", onDragEnd, true);

    return () => {
      if (activeEditor === editor) activeEditor = null;
      document.documentElement.classList.remove(WEBKIT_CLASS);
      document.removeEventListener("dragstart", onDragStartCapture, true);
      document.removeEventListener("dragend", onDragEnd, true);
      document.removeEventListener("drop", onDragEnd, true);
      DataTransfer.prototype.setDragImage = nativeSetDragImage;
      clearSafariDragSession();
    };
  }, [editor]);
}
