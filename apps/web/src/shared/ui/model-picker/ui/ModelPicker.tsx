"use client";

import { createPortal } from "react-dom";
import ModelPickerDropdown from "./ModelPickerDropdown";
import { ModelPickerChevron } from "./ModelPickerIcons";
import { modelPickerDropdownStyle } from "../lib/utils";
import type { ModelPickerProps } from "../model/types";
import { useModelPicker } from "@/shared/ui/model-picker/model/useModelPicker";

export type { ModelOption, ModelPickerSection } from "../model/types";
export { BrainIcon, SearchIcon, VisionIcon, ImageGenIcon } from "./ModelPickerIcons";

export default function ModelPicker({
  icon,
  value,
  options = [],
  sections,
  ariaLabel,
  dropdownClassName,
  className,
  ...rest
}: ModelPickerProps) {
  const picker = useModelPicker({
    value,
    options,
    sections,
    className,
    ...rest,
  });

  return (
    <div
      className={`model-picker${picker.open ? " is-open" : ""}${picker.isDisabled ? " is-disabled" : ""}${className ? ` ${className}` : ""}`}
    >
      <button
        ref={picker.btnRef}
        type="button"
        className="model-picker-btn"
        disabled={picker.isDisabled}
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={picker.open}
        onClick={picker.onTriggerClick}
      >
        {icon ? <span className="model-picker-icon">{icon}</span> : null}
        <span className="model-picker-label">{picker.label}</span>
        <ModelPickerChevron />
      </button>
      {picker.open && !picker.isDisabled && picker.pos && typeof document !== "undefined"
        ? createPortal(
            <div
              ref={picker.dropdownRef}
              className={`model-picker-dropdown${picker.isComposerPicker ? " model-picker-dropdown--composer" : ""}${dropdownClassName ? ` ${dropdownClassName}` : ""}`}
              role="listbox"
              style={modelPickerDropdownStyle(picker.pos, picker.isComposerPicker)}
            >
              <ModelPickerDropdown
                value={value}
                options={options}
                sections={sections}
                emptyValue={rest.emptyValue}
                emptyLabel={rest.emptyLabel}
                onSelect={picker.onSelect}
              />
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}
