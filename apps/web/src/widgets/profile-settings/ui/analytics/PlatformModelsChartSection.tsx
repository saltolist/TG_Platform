"use client";

import { ChartSeriesSelector, MultiSeriesTrendChart, type TrendSeriesRow } from "@/widgets/charts";
import ModelPicker from "@/shared/ui/model-picker";
import PlatformMiniMetric from "@/widgets/profile-settings/ui/analytics/PlatformMiniMetric";
import { PLATFORM_ANALYTICS_PERIODS } from "@/shared/lib/platformAnalyticsPeriods";
import { PLATFORM_MODEL_FILTERS, type ModelFilterId } from "@/shared/lib/platformModelFilters";
import type { PlatformModelUsage, PlatformModelUsageTotals } from "@/shared/lib/profile/platformAnalytics";
import { getTrendPointCost } from "@/shared/lib/profile/platformAnalytics";
import { formatCompact, formatNumber, formatTrendDollar } from "@/shared/lib/trendChart/math";

type Props = {
  period: number;
  onPeriodChange: (next: number) => void;
  periodInHeader: boolean;
  modelType: ModelFilterId;
  onModelTypeChange: (next: ModelFilterId) => void;
  modelTotals: PlatformModelUsageTotals;
  chartLabels: string[];
  chartTitle: string;
  selectedModels: PlatformModelUsage[];
  visibleCostTrendSeries: TrendSeriesRow[];
  selectorItems: { id: string; label: string; color: string }[];
  isVisible: (id: string) => boolean;
  onVisibleChange: (id: string, next: boolean) => void;
  compactAxisLabels: boolean;
};

export default function PlatformModelsChartSection({
  period,
  onPeriodChange,
  periodInHeader,
  modelType,
  onModelTypeChange,
  modelTotals,
  chartLabels,
  chartTitle,
  selectedModels,
  visibleCostTrendSeries,
  selectorItems,
  isVisible,
  onVisibleChange,
  compactAxisLabels,
}: Props) {
  return (
    <div className="profile-section platform-analytics-section profile-checkbox-scope">
      <div className="analytics-card-head">
        <div>
          <div className="profile-section-title">Аналитика моделей</div>
        </div>
        <div className="model-filter-stack model-filter-stack--with-series">
          <ModelPicker
            ariaLabel="Тип модели"
            className="profile-model-picker"
            value={modelType}
            options={PLATFORM_MODEL_FILTERS.map((type) => ({
              id: type.id,
              label: type.label,
            }))}
            placement="down"
            onChange={(id) => onModelTypeChange(id as ModelFilterId)}
          />
          <ChartSeriesSelector
            variant="profile"
            label="Модели"
            items={selectorItems}
            isVisible={isVisible}
            onVisibleChange={onVisibleChange}
          />
          {!periodInHeader ? (
            <ModelPicker
              ariaLabel="Период"
              className="profile-model-picker platform-period-picker--in-card"
              value={String(period)}
              options={PLATFORM_ANALYTICS_PERIODS.map((item, index) => ({
                id: String(index),
                label: item.label,
              }))}
              placement="down"
              onChange={(id) => onPeriodChange(Number(id))}
            />
          ) : null}
        </div>
      </div>

      <div className="model-analytics-summary">
        <PlatformMiniMetric label="Запросы" value={formatNumber(modelTotals.calls)} />
        <PlatformMiniMetric label="Токены" value={formatCompact(modelTotals.tokens)} />
        <PlatformMiniMetric label="Стоимость" value={`$${modelTotals.cost.toFixed(2)}`} />
      </div>

      <div className="section-title analytics-chart-title">{chartTitle}</div>
      <MultiSeriesTrendChart
        labels={chartLabels}
        series={visibleCostTrendSeries}
        period={period}
        compactAxisLabels={compactAxisLabels}
        title={chartTitle}
        formatAxisValue={formatTrendDollar}
        getDotPrimaryLine={(_, value) => `${formatNumber(value)} запросов`}
        getDotExtraLines={(row, value, pointIndex) => {
          const model = selectedModels.find((item) => item.id === row.id);
          if (!model) return [];
          const ratio = model.calls > 0 ? value / model.calls : 0;
          const tokens = Math.round(model.tokens * ratio);
          const cost = getTrendPointCost(model, pointIndex);
          return [
            `${formatCompact(tokens)} токенов`,
            formatTrendDollar(cost, cost),
          ];
        }}
      />
    </div>
  );
}
