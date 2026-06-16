"use client";

import { useCallback, useLayoutEffect, useRef, useState, type MouseEvent } from "react";
import { useFloatingPanelScrollListeners } from "@/shared/lib/hooks/useFloatingPanelScrollListeners";
import { useOverlayDismissOnPointer } from "@/shared/lib/hooks/useOverlayDismissOnPointer";
import {
  computeModelPickerPos,
  flattenModelOptions,
  resolveModelPickerLabel,
} from "@/shared/ui/model-picker/lib/utils";
import type { ModelPickerPos, ModelPickerProps } from "@/shared/ui/model-picker/model/types";

export function useModelPicker({
  value,
  options = [],
  sections,
  onChange,
  emptyValue,
  emptyLabel,
  placeholderLabel,
  disabled,
  placement = "up",
  className,
  buttonLabelFormatter,
}: ModelPickerProps) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<ModelPickerPos | null>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const isComposerPicker = className?.includes("composer-model-picker") ?? false;

  const updatePos = useCallback(() => {
    const btn = btnRef.current;
    if (!btn) return;
    setPos(computeModelPickerPos(btn, dropdownRef.current, placement, isComposerPicker));
  }, [placement, isComposerPicker]);

  useLayoutEffect(() => {
    if (!open) return;
    updatePos();
    const raf = requestAnimationFrame(updatePos);
    return () => cancelAnimationFrame(raf);
  }, [open, updatePos]);

  const close = useCallback(() => setOpen(false), []);

  const { consumeSuppressTriggerClick } = useOverlayDismissOnPointer({
    open,
    onClose: close,
    contentRef: dropdownRef,
    triggerRef: btnRef,
  });

  useFloatingPanelScrollListeners({
    open,
    onReflow: updatePos,
    onClose: close,
  });

  const flatOptions = flattenModelOptions(options, sections);
  const label = resolveModelPickerLabel(value, flatOptions, {
    emptyValue,
    emptyLabel,
    placeholderLabel,
    buttonLabelFormatter,
  });
  const isDisabled = disabled || (flatOptions.length === 0 && emptyValue === undefined);

  const onTriggerClick = useCallback(
    (e: MouseEvent) => {
      e.stopPropagation();
      if (consumeSuppressTriggerClick()) return;
      if (!isDisabled) setOpen((v) => !v);
    },
    [consumeSuppressTriggerClick, isDisabled],
  );

  const onSelect = useCallback(
    (id: string) => {
      onChange(id);
      setOpen(false);
    },
    [onChange],
  );

  return {
    open,
    pos,
    btnRef,
    dropdownRef,
    label,
    isDisabled,
    isComposerPicker,
    onTriggerClick,
    onSelect,
    flatOptions,
  };
}
