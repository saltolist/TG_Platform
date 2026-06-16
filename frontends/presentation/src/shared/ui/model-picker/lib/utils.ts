import type { CSSProperties } from "react";
import { clampFloatingPanelLeft } from "@/shared/lib/floatingPanel";
import type { ModelOption, ModelPickerPos, ModelPickerSection } from "../model/types";

export function flattenModelOptions(
  options: ModelOption[],
  sections?: ModelPickerSection[],
): ModelOption[] {
  return sections ? sections.flatMap((s) => s.options) : options;
}

export function resolveModelPickerLabel(
  value: string,
  flatOptions: ModelOption[],
  {
    emptyValue,
    emptyLabel,
    placeholderLabel,
    buttonLabelFormatter,
  }: {
    emptyValue?: string;
    emptyLabel?: string;
    placeholderLabel?: string;
    buttonLabelFormatter?: (opt: ModelOption) => string;
  },
): string {
  const isEmpty = emptyValue !== undefined && value === emptyValue;
  const selected = !isEmpty ? flatOptions.find((o) => o.id === value) : null;
  if (selected) {
    return buttonLabelFormatter ? buttonLabelFormatter(selected) : selected.label;
  }
  if (isEmpty && emptyLabel) return emptyLabel;
  return placeholderLabel ?? "Выбрать";
}

export function computeModelPickerPos(
  btn: HTMLButtonElement,
  dropdown: HTMLDivElement | null,
  placement: "up" | "down",
  isComposerPicker: boolean,
): ModelPickerPos {
  const r = btn.getBoundingClientRect();
  const minWidth = Math.max(r.width, isComposerPicker ? r.width : 140);
  const panelWidth = dropdown?.offsetWidth ?? minWidth;
  const left = clampFloatingPanelLeft(r.left, panelWidth);
  if (placement === "down") {
    return { mode: "down", top: r.bottom + 6, left, width: r.width };
  }
  return { mode: "up", bottom: window.innerHeight - r.top + 6, left, width: r.width };
}

export function modelPickerDropdownStyle(
  pos: ModelPickerPos,
  isComposerPicker: boolean,
): CSSProperties {
  const widthProps = isComposerPicker
    ? { width: "max-content" as const, minWidth: pos.width, maxWidth: "none" as const }
    : { minWidth: pos.width };

  if (pos.mode === "down") {
    return { top: pos.top, left: pos.left, ...widthProps };
  }
  return { bottom: pos.bottom, left: pos.left, ...widthProps };
}
