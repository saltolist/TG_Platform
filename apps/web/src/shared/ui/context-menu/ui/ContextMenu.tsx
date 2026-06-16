"use client";

import { createPortal } from "react-dom";

import { FLOATING_PANEL_EDGE_MARGIN_PX } from "@/shared/lib/floatingPanel";
import { ContextMenuItems } from "@/shared/ui/context-menu/ContextMenuItems";
import type { ContextMenuProps } from "@/shared/ui/context-menu/contextMenuTypes";
import { useContextMenu } from "@/shared/ui/context-menu/model/useContextMenu";

export type { CtxMenuItem } from "@/shared/ui/context-menu/contextMenuTypes";

export function ContextMenu({
  items,
  trigger = "•••",
  dropdownClassName = "",
  triggerAriaLabel,
  ...rest
}: ContextMenuProps) {
  const {
    open,
    wrapRef,
    btnRef,
    dropdownRef,
    onTriggerClick,
    onItemSelect,
    triggerBtnClass,
    wrapClass,
    panelStyle,
    matchTriggerWidth,
    align,
  } = useContextMenu({ items, dropdownClassName, ...rest });

  return (
    <div ref={wrapRef} className={wrapClass || undefined}>
      <button
        ref={btnRef}
        className={triggerBtnClass}
        type="button"
        aria-label={triggerAriaLabel}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={onTriggerClick}
      >
        {trigger}
      </button>
      {rest.portal && open && typeof document !== "undefined"
        ? createPortal(
            <div
              ref={dropdownRef}
              className={`ctx-dropdown ctx-dropdown-portal open${dropdownClassName ? ` ${dropdownClassName}` : ""}`}
              style={{
                position: "fixed",
                top: panelStyle.top,
                left: panelStyle.left,
                right: "auto",
                minWidth: panelStyle.minWidth,
                width: panelStyle.width,
                maxWidth: matchTriggerWidth
                  ? panelStyle.width
                  : `min(280px, calc(100vw - ${FLOATING_PANEL_EDGE_MARGIN_PX * 2}px))`,
                zIndex: 2000,
                visibility: panelStyle.visible ? "visible" : "hidden",
                pointerEvents: panelStyle.visible ? "auto" : "none",
              }}
            >
              <ContextMenuItems items={items} onSelect={onItemSelect} />
            </div>,
            document.body,
          )
        : null}
      {!rest.portal ? (
        <div
          ref={dropdownRef}
          className={`ctx-dropdown${dropdownClassName ? ` ${dropdownClassName}` : ""}${open ? " open" : ""}`}
          style={align === "left" ? { left: 0, right: "auto" } : undefined}
        >
          <ContextMenuItems items={items} onSelect={onItemSelect} />
        </div>
      ) : null}
    </div>
  );
}
