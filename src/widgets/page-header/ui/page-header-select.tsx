"use client";

import { useMemo } from "react";

import { useMobile760 } from "@/shared/lib/hooks/useMobile760";
import { ContextMenu } from "@/shared/ui/context-menu";

export type PageHeaderSelectOption = { value: string; label: string };

type PageHeaderSelectProps = {
  value: string;
  options: readonly PageHeaderSelectOption[];
  onChange: (value: string) => void;
  ariaLabel: string;
  className?: string;
  chevron?: "both" | "down";
  tightWidth?: boolean;
};

function PageHeaderSelectChevron({
  inline,
  variant = "both",
}: {
  inline?: boolean;
  variant?: "both" | "down";
}) {
  return (
    <svg
      className={`page-header-select-chevron${inline ? " page-header-select-chevron--inline" : ""}`}
      viewBox="0 0 24 24"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth={2.4}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {variant === "down" ? (
        <polyline points="8 10 12 14 16 10" />
      ) : (
        <>
          <polyline points="8 9 12 5 16 9" />
          <polyline points="8 15 12 19 16 15" />
        </>
      )}
    </svg>
  );
}

export function PageHeaderSelect({
  value,
  options,
  onChange,
  ariaLabel,
  className,
  chevron = "both",
  tightWidth = false,
}: PageHeaderSelectProps) {
  const isMobile = useMobile760();

  const currentLabel = useMemo(
    () => options.find((o) => o.value === value)?.label ?? "",
    [options, value],
  );

  const panelMinWidth = useMemo(() => {
    const longest = options.reduce((max, o) => Math.max(max, o.label.length), 0);
    return Math.min(420, Math.max(160, longest * 8 + 64));
  }, [options]);

  const selectClass = className ? `page-header-select ${className}` : "page-header-select";

  return (
    <div
      className={`page-header-select-wrap${isMobile ? " page-header-select-wrap--mobile" : ""}${
        tightWidth ? " page-header-select-wrap--tight" : ""
      }`}
    >
      <ContextMenu
        className="page-header-select-ctx"
        triggerVariant="custom"
        triggerClassName={selectClass}
        trigger={
          <span className="page-header-select-trigger">
            <span className="page-header-select-trigger-text">{currentLabel}</span>
            <PageHeaderSelectChevron inline variant={chevron} />
          </span>
        }
        triggerAriaLabel={ariaLabel}
        portal
        align="right"
        panelMinWidth={panelMinWidth}
        dropdownClassName="ctx-dropdown--page-header-control ctx-dropdown--page-header-select"
        items={options.map((o) => ({
          label: o.label,
          active: o.value === value,
          onClick: () => onChange(o.value),
        }))}
      />
    </div>
  );
}
