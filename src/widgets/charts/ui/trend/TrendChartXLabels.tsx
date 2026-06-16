import { getTrendPointXPercent } from "@/shared/lib/trendChart/periodLabels";

type Props = {
  labels: string[];
  compactAxisLabels: boolean;
  pointEdgeInsetPercent: number;
};

export default function TrendChartXLabels({
  labels,
  compactAxisLabels,
  pointEdgeInsetPercent,
}: Props) {
  return (
    <div className={`trend-labels${compactAxisLabels ? " trend-labels--hourly" : ""}`}>
      {labels.map((label, index) => (
        <span
          key={`${label}-${index}`}
          style={{ left: `${getTrendPointXPercent(index, labels.length, pointEdgeInsetPercent)}%` }}
        >
          {label}
        </span>
      ))}
    </div>
  );
}
