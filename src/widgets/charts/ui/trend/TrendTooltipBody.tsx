import TrendTooltipTitle from "@/widgets/charts/ui/trend/TrendTooltipTitle";

type Props = {
  label: string;
  growth?: string;
  periodLabel: string;
  primaryLine: string;
  rangeFromStart?: string;
  percentGrowth?: string;
  extraLines: string[];
};

export default function TrendTooltipBody({
  label,
  growth,
  periodLabel,
  primaryLine,
  rangeFromStart,
  percentGrowth,
  extraLines,
}: Props) {
  return (
    <>
      <TrendTooltipTitle label={label} growth={growth} />
      <span className="trend-tooltip-period">{periodLabel}</span>
      <em className="trend-tooltip-metric">{primaryLine}</em>
      {rangeFromStart ? <span className="trend-tooltip-range">{rangeFromStart}</span> : null}
      {percentGrowth ? <span className="trend-tooltip-percent">{percentGrowth}</span> : null}
      {extraLines.map((line) => (
        <em key={line}>{line}</em>
      ))}
    </>
  );
}
