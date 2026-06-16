import type { ReactNode } from "react";

export type ModelOption = { id: string; label: string };
export type ModelPickerSection = { title: string; options: ModelOption[] };

export type ModelPickerPos =
  | { mode: "up"; bottom: number; left: number; width: number }
  | { mode: "down"; top: number; left: number; width: number };

export type ModelPickerProps = {
  icon?: ReactNode;
  value: string;
  options?: ModelOption[];
  sections?: ModelPickerSection[];
  onChange: (id: string) => void;
  emptyValue?: string;
  emptyLabel?: string;
  placeholderLabel?: string;
  disabled?: boolean;
  ariaLabel?: string;
  placement?: "up" | "down";
  className?: string;
  dropdownClassName?: string;
  /** Подпись на кнопке; пункты меню — из options/sections.label */
  buttonLabelFormatter?: (opt: ModelOption) => string;
};
