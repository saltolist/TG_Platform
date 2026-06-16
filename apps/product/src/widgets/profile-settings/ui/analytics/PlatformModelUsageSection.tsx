import ModelUsageBar from "@/widgets/profile-settings/ui/analytics/ModelUsageBar";
import type {
  PlatformModelUsage,
  PlatformModelUsageTotals,
} from "@/shared/lib/profile/platformAnalytics";

type Props = {
  isAllTypes: boolean;
  selectedModels: PlatformModelUsage[];
  modelTotals: PlatformModelUsageTotals;
};

export default function PlatformModelUsageSection({
  isAllTypes,
  selectedModels,
  modelTotals,
}: Props) {
  return (
    <div className="profile-section platform-analytics-section">
      <div className="profile-section-title platform-section-title-spaced">
        {isAllTypes ? "Типы моделей за период" : "Модели за период"}
      </div>
      <div className="model-usage-grid">
        <div className="model-usage-head">
          <span>{isAllTypes ? "Тип" : "Модель"}</span>
          <span className="model-usage-head-bar" aria-hidden />
          <span>Запросы</span>
          <span>Токены</span>
          <span>Стоимость</span>
        </div>
        {selectedModels.map((model) => (
          <ModelUsageBar key={model.id} model={model} totals={modelTotals} />
        ))}
      </div>
    </div>
  );
}
