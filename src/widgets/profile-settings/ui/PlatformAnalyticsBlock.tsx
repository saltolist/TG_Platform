"use client";

import PlatformActivitySection from "@/widgets/profile-settings/ui/analytics/PlatformActivitySection";
import PlatformModelUsageSection from "@/widgets/profile-settings/ui/analytics/PlatformModelUsageSection";
import PlatformModelsChartSection from "@/widgets/profile-settings/ui/analytics/PlatformModelsChartSection";
import { usePlatformAnalyticsBlock } from "@/widgets/profile-settings/model/usePlatformAnalyticsBlock";
import { useChannelConnected } from "@/entities/channel";
import { ConnectChannelEmptyState } from "@/features/connect-channel";

type Props = {
  period: number;
  onPeriodChange: (next: number) => void;
  periodInHeader?: boolean;
};

export default function PlatformAnalyticsBlock({
  period,
  onPeriodChange,
  periodInHeader = false,
}: Props) {
  const analytics = usePlatformAnalyticsBlock({ period, onPeriodChange, periodInHeader });
  const { isConnected: isChannelConnected, isLoading: isChannelLoading } = useChannelConnected();

  if (isChannelLoading) {
    return <p className="screen-placeholder">Загрузка аналитики…</p>;
  }

  if (!isChannelConnected) {
    return <ConnectChannelEmptyState feature="аналитике платформы" icon="📈" />;
  }

  return (
    <>
      <PlatformModelsChartSection
        period={analytics.period}
        onPeriodChange={analytics.onPeriodChange}
        periodInHeader={analytics.periodInHeader}
        modelType={analytics.modelType}
        onModelTypeChange={analytics.setModelType}
        modelTotals={analytics.modelTotals}
        chartLabels={analytics.chartLabels}
        chartTitle={analytics.chartTitle}
        selectedModels={analytics.selectedModels}
        visibleCostTrendSeries={analytics.visibleCostTrendSeries}
        selectorItems={analytics.selectorItems}
        isVisible={analytics.isVisible}
        onVisibleChange={analytics.setVisible}
        compactAxisLabels={analytics.compactAxisLabels}
      />
      <PlatformModelUsageSection
        isAllTypes={analytics.isAllTypes}
        selectedModels={analytics.selectedModels}
        modelTotals={analytics.modelTotals}
      />
      <PlatformActivitySection />
    </>
  );
}
