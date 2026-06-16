"use client";

import { useMemo } from "react";

import { ContextMenu } from "@/shared/ui/context-menu";

export type FilterTabSelectOption<T extends string = string> = {
  value: T;
  label: string;
};

type Props<T extends string> = {
  value: T;
  options: readonly FilterTabSelectOption<T>[];
  onChange: (value: T) => void;
  ariaLabel: string;
  className?: string;
};

function ChevronDown() {
  return (
    <svg
      className="filter-tab-chevron"
      viewBox="0 0 24 24"
      width={14}
      height={14}
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

export default function FilterTabSelect<T extends string>({
  value,
  options,
  onChange,
  ariaLabel,
  className,
}: Props<T>) {
  const label = useMemo(
    () => options.find((o) => o.value === value)?.label ?? options[0]?.label ?? "",
    [options, value],
  );

  const panelMinWidth = useMemo(() => {
    const longest = options.reduce((max, o) => Math.max(max, o.label.length), 0);
    return Math.min(320, Math.max(160, longest * 8 + 48));
  }, [options]);

  return (
    <ContextMenu
      className={className}
      triggerVariant="custom"
      triggerClassName="page-header-control active filter-tab--dropdown"
      trigger={
        <>
          <span className="filter-tab--dropdown-label">{label}</span>
          <ChevronDown />
        </>
      }
      triggerAriaLabel={ariaLabel}
      portal
      align="left"
      panelMinWidth={panelMinWidth}
      dropdownClassName="ctx-dropdown--page-header-control ctx-dropdown--page-header-select"
      items={options.map((o) => ({
        label: o.label,
        active: o.value === value,
        onClick: () => onChange(o.value),
      }))}
    />
  );
}
