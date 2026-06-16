"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState, type MouseEvent } from "react";

import { useFloatingPanelScrollListeners } from "@/shared/lib/hooks/useFloatingPanelScrollListeners";
import { useOverlayDismissOnPointer } from "@/shared/lib/hooks/useOverlayDismissOnPointer";
import { computePortalLayout, DROPDOWN_MIN_W } from "@/shared/ui/context-menu/contextMenuUtils";
import type {
  ContextMenuProps,
  CtxMenuItem,
  PortalLayout,
  PortalLayoutOpts,
} from "@/shared/ui/context-menu/contextMenuTypes";

export function useContextMenu({
  items,
  align = "right",
  portal = false,
  className = "",
  triggerVariant = "menu",
  triggerClassName = "",
  panelMinWidth,
  matchTriggerWidth = false,
  onOpenChange,
}: ContextMenuProps) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const [portalLayout, setPortalLayout] = useState<PortalLayout | null>(null);
  const layoutOptsRef = useRef<PortalLayoutOpts>({
    align,
    matchTriggerWidth,
    panelMinWidth,
  });
  const onOpenChangeRef = useRef(onOpenChange);
  const prevOpenRef = useRef(open);

  useEffect(() => {
    layoutOptsRef.current = { align, matchTriggerWidth, panelMinWidth };
    onOpenChangeRef.current = onOpenChange;
  });

  useEffect(() => {
    if (prevOpenRef.current === open) return;
    prevOpenRef.current = open;
    onOpenChangeRef.current?.(open);
  }, [open]);

  const syncPortalLayout = useCallback(() => {
    const btn = btnRef.current;
    if (!btn) return;
    setPortalLayout(computePortalLayout(btn, dropdownRef.current, layoutOptsRef.current));
  }, []);

  useLayoutEffect(() => {
    if (!open || !portal) {
      setPortalLayout(null);
      return;
    }
    syncPortalLayout();
    if (matchTriggerWidth) return;
    syncPortalLayout();
  }, [open, portal, matchTriggerWidth, syncPortalLayout, items]);

  const closePortal = useCallback(() => {
    setOpen(false);
    setPortalLayout(null);
  }, []);

  const { consumeSuppressTriggerClick } = useOverlayDismissOnPointer({
    open,
    onClose: closePortal,
    contentRef: dropdownRef,
    triggerRef: btnRef,
  });

  const openPortal = useCallback(() => {
    const btn = btnRef.current;
    if (portal && btn) {
      setPortalLayout(computePortalLayout(btn, null, layoutOptsRef.current));
    }
    setOpen(true);
  }, [portal]);

  const togglePortal = useCallback(() => {
    if (open) closePortal();
    else openPortal();
  }, [open, closePortal, openPortal]);

  useFloatingPanelScrollListeners({
    open: open && portal,
    onReflow: syncPortalLayout,
    onClose: closePortal,
  });

  const onTriggerClick = useCallback(
    (e: MouseEvent) => {
      e.stopPropagation();
      if (consumeSuppressTriggerClick()) return;
      if (portal) togglePortal();
      else setOpen((v) => !v);
    },
    [consumeSuppressTriggerClick, portal, togglePortal],
  );

  const onItemSelect = useCallback(
    (item: CtxMenuItem) => {
      if (item.disabled) return;
      closePortal();
      item.onClick?.();
    },
    [closePortal],
  );

  const triggerBtnClass =
    triggerVariant === "custom" ? triggerClassName || "ctx-btn" : "ctx-btn";
  const wrapClass =
    triggerVariant === "custom" ? className : `ctx-wrap${className ? ` ${className}` : ""}`;

  const basePanelMinWidth = panelMinWidth ?? DROPDOWN_MIN_W;
  const panelStyle = portalLayout ?? {
    top: 0,
    left: 0,
    minWidth: basePanelMinWidth,
    visible: false,
  };

  return {
    open,
    wrapRef,
    btnRef,
    dropdownRef,
    onTriggerClick,
    onItemSelect,
    closePortal,
    triggerBtnClass,
    wrapClass,
    panelStyle,
    basePanelMinWidth,
    align,
    matchTriggerWidth,
  };
}
