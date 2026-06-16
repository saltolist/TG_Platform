"use client";

import {
  ANALYTICS_PERIOD_OPTIONS,
  type AnalyticsPeriod,
} from "@/shared/data/analytics-seed";
import { PageHeaderTabList } from "@/shared/ui/page-header-tab-group";

type AnalyticsPeriodFilterProps = {
  value: AnalyticsPeriod;
  onChange: (value: AnalyticsPeriod) => void;
  className?: string;
};

export function AnalyticsPeriodFilter({ value, onChange, className }: AnalyticsPeriodFilterProps) {
  return (
    <PageHeaderTabList
      value={value}
      options={ANALYTICS_PERIOD_OPTIONS}
      onChange={onChange}
      ariaLabel="Период аналитики"
      className={className}
      wrap
    />
  );
}
