import { clampFloatingPanelLeft } from "@/shared/lib/floatingPanel";

import type { PortalLayout, PortalLayoutOpts } from "./contextMenuTypes";

export const DROPDOWN_MIN_W = 200;
export const DROPDOWN_OFFSET = 12;

export function computePortalLayout(
  btn: HTMLButtonElement,
  dropdown: HTMLDivElement | null,
  { align, matchTriggerWidth, panelMinWidth }: PortalLayoutOpts,
): PortalLayout {
  const r = btn.getBoundingClientRect();
  const baseMin = panelMinWidth ?? DROPDOWN_MIN_W;

  if (matchTriggerWidth) {
    const panelWidth = Math.max(baseMin, Math.round(r.width));
    const preferredLeft = align === "right" ? r.right - panelWidth : r.left;
    return {
      top: r.bottom + DROPDOWN_OFFSET,
      left: clampFloatingPanelLeft(preferredLeft, panelWidth),
      minWidth: panelWidth,
      width: panelWidth,
      visible: true,
    };
  }

  const measured = dropdown?.offsetWidth ?? 0;
  const panelWidth = measured > 0 ? Math.max(baseMin, measured) : baseMin;
  const preferredLeft = align === "right" ? r.right - panelWidth : r.left;
  return {
    top: r.bottom + DROPDOWN_OFFSET,
    left: clampFloatingPanelLeft(preferredLeft, panelWidth),
    minWidth: panelWidth,
    visible: measured > 0,
  };
}
