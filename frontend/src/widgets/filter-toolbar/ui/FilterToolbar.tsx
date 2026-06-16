"use client";

import type { ReactNode } from "react";

import { useMobile760 } from "@/shared/lib/hooks/useMobile760";
import { FilterTabSelect, type FilterTabSelectOption } from "@/shared/ui/filter-tab-select";
import { PageHeaderControl } from "@/shared/ui/page-header-tab-group";

export type FilterToolbarTab<T extends string = string> = FilterTabSelectOption<T>;

type Props<T extends string> = {
  tabs?: readonly FilterToolbarTab<T>[];
  value?: T;
  onChange?: (value: T) => void;
  mobileFilter?: ReactNode;
  mobileTabs?: readonly FilterToolbarTab<T>[];
  tabAriaLabel?: string;
  selectClassName?: string;
  action?: ReactNode;
  className?: string;
  width?: "content" | "composer";
};

export default function FilterToolbar<T extends string>({
  tabs,
  value,
  onChange,
  mobileFilter,
  mobileTabs,
  tabAriaLabel = "Фильтр",
  selectClassName,
  action,
  className = "",
  width = "content",
}: Props<T>) {
  const isMobile = useMobile760();
  const hasTabs = tabs != null && tabs.length > 0 && value != null && onChange != null;
  const showFilters = hasTabs || mobileFilter != null;

  return (
    <div className={`filter-toolbar filter-toolbar--${width}${className ? ` ${className}` : ""}`}>
      {showFilters ? (
        <div className="filter-toolbar__filters">
          {isMobile && mobileFilter ? (
            mobileFilter
          ) : isMobile && hasTabs ? (
            <FilterTabSelect
              className={selectClassName}
              value={value!}
              options={mobileTabs ?? tabs!}
              onChange={onChange!}
              ariaLabel={tabAriaLabel}
            />
          ) : hasTabs ? (
            tabs!.map(({ value: tabValue, label }) => (
              <PageHeaderControl
                key={tabValue}
                active={value === tabValue}
                onClick={() => onChange!(tabValue)}
              >
                {label}
              </PageHeaderControl>
            ))
          ) : null}
        </div>
      ) : null}
      {action ? <div className="filter-toolbar__action">{action}</div> : null}
    </div>
  );
}
