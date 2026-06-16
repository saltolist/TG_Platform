"use client";

import { useCallback, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";
import { Checkbox } from "@/shared/ui/checkbox";
import { clampFloatingPanelLeft } from "@/shared/lib/floatingPanel";
import { useFloatingPanelScrollListeners } from "@/shared/lib/hooks/useFloatingPanelScrollListeners";
import { useOverlayDismissOnPointer } from "@/shared/lib/hooks/useOverlayDismissOnPointer";

export type ChartSeriesSelectorItem = {
  id: string;
  label: string;
  color: string;
};

type ChartSeriesSelectorProps = {
  label: string;
  items: ChartSeriesSelectorItem[];
  isVisible: (id: string) => boolean;
  onVisibleChange: (id: string, visible: boolean) => void;
  /** В профиле — те же pill-селекторы, что у выбора модели в настройках. */
  variant?: "default" | "profile";
};

function PickerChevron() {
  return (
    <svg
      className="model-picker-chevron"
      viewBox="0 0 24 24"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth={2.4}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <polyline points="6 9 12 15 18 9" />
    </svg>
  );
}

export default function ChartSeriesSelector({
  label,
  items,
  isVisible,
  onVisibleChange,
  variant = "default",
}: ChartSeriesSelectorProps) {
  const isProfile = variant === "profile";
  const [open, setOpen] = useState(false);
  const [panelPos, setPanelPos] = useState<{ top: number; left: number; width: number } | null>(
    null,
  );
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  const visibleCount = useMemo(
    () => items.filter((item) => isVisible(item.id)).length,
    [items, isVisible],
  );

  const triggerLabel = useMemo(() => {
    if (items.length === 0) return label;
    return `${label} ${visibleCount}/${items.length}`;
  }, [items.length, label, visibleCount]);

  const updatePanelPos = useCallback(() => {
    const trigger = triggerRef.current;
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    const minPanelWidth = Math.max(rect.width, isProfile ? rect.width : 220);
    const panelWidth = panelRef.current?.offsetWidth ?? minPanelWidth;
    setPanelPos({
      top: rect.bottom + 6,
      left: clampFloatingPanelLeft(rect.left, panelWidth),
      width: rect.width,
    });
  }, [isProfile]);

  useLayoutEffect(() => {
    if (!open) return;
    updatePanelPos();
    const raf = requestAnimationFrame(updatePanelPos);
    return () => cancelAnimationFrame(raf);
  }, [open, updatePanelPos]);

  const { consumeSuppressTriggerClick } = useOverlayDismissOnPointer({
    open,
    onClose: () => setOpen(false),
    contentRef: panelRef,
    triggerRef: triggerRef,
  });

  useFloatingPanelScrollListeners({
    open,
    onReflow: updatePanelPos,
    onClose: () => setOpen(false),
  });

  const rootClassName = isProfile
    ? `model-picker profile-model-picker chart-series-selector chart-series-selector--profile${open ? " is-open" : ""}`
    : `chart-series-selector${open ? " is-open" : ""}`;

  const triggerClassName = isProfile ? "model-picker-btn" : "chart-series-selector-trigger";
  const labelClassName = isProfile ? "model-picker-label" : "chart-series-selector-trigger-text";
  const panelClassName = isProfile
    ? "model-picker-dropdown chart-series-selector-panel chart-series-selector-panel--profile profile-checkbox-scope"
    : "chart-series-selector-panel profile-checkbox-scope";

  return (
    <div className={rootClassName}>
      <button
        ref={triggerRef}
        type="button"
        className={triggerClassName}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={triggerLabel}
        disabled={items.length === 0}
        onClick={(e) => {
          e.stopPropagation();
          if (consumeSuppressTriggerClick()) return;
          setOpen((value) => !value);
        }}
      >
        <span className={labelClassName}>{triggerLabel}</span>
        {isProfile ? <PickerChevron /> : null}
      </button>
      {open && panelPos && typeof document !== "undefined"
        ? createPortal(
            <div
              ref={panelRef}
              className={panelClassName}
              role="listbox"
              aria-label={label}
              style={{
                top: panelPos.top,
                left: panelPos.left,
                minWidth: Math.max(panelPos.width, isProfile ? panelPos.width : 220),
                maxWidth: "min(280px, calc(100vw - 24px))",
              }}

            >
              {items.map((item) => (
                <label
                  key={item.id}
                  className="profile-checkbox-label chart-series-selector-item"
                  onMouseLeave={(event) => {
                    const related = event.relatedTarget as Node | null;
                    if (related && event.currentTarget.contains(related)) return;
                    event.currentTarget
                      .querySelector<HTMLInputElement>("input.chart-series-selector-checkbox")
                      ?.classList.remove("profile-checkbox--suppress-hover");
                  }}
                >
                  <Checkbox
                    className="chart-series-selector-checkbox"
                    checked={isVisible(item.id)}
                    onChange={(event) => onVisibleChange(item.id, event.target.checked)}
                    aria-label={`${item.label}: показывать на графике`}
                    style={{ "--series-color": item.color } as CSSProperties}
                  />
                  <span className="chart-series-selector-item-label">{item.label}</span>
                </label>
              ))}
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}
