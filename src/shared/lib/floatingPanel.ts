/** Минимальный отступ плавающих меню от краёв viewport (мобильная и десктоп). */
export const FLOATING_PANEL_EDGE_MARGIN_PX = 12;

export function clampFloatingPanelLeft(
  preferredLeft: number,
  panelWidth: number,
  margin: number = FLOATING_PANEL_EDGE_MARGIN_PX,
): number {
  if (typeof window === "undefined") return preferredLeft;
  const width = Math.max(0, panelWidth);
  const maxLeft = Math.max(margin, window.innerWidth - width - margin);
  return Math.round(Math.max(margin, Math.min(maxLeft, preferredLeft)));
}
