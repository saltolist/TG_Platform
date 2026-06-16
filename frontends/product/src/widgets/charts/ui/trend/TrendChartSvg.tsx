import type { TrendChartRow } from "@/shared/lib/trendChart/chartTypes";
import {
  TREND_CHART_WIDTH,
  buildTrendLineGradientStops,
  sanitizeSvgId,
} from "@/shared/lib/trendChart/math";

type Props = {
  title: string;
  gridRows: { y: number; label: string }[];
  chartRows: TrendChartRow[];
  hoveredLineHighlights: Map<string, number>;
};

export default function TrendChartSvg({
  title,
  gridRows,
  chartRows,
  hoveredLineHighlights,
}: Props) {
  return (
    <svg
      className="trend-chart"
      viewBox={`0 0 ${TREND_CHART_WIDTH} 100`}
      preserveAspectRatio="none"
      role="img"
      aria-label={title}
    >
      {gridRows.map((row) => (
        <polyline
          key={row.label}
          className="trend-grid-line"
          points={`0,${row.y.toFixed(1)} ${TREND_CHART_WIDTH},${row.y.toFixed(1)}`}
        />
      ))}
      <defs>
        {chartRows.map((row) => {
          const highlightX = hoveredLineHighlights.get(row.id);
          if (highlightX === undefined) return null;
          const gradientId = `trend-grad-${sanitizeSvgId(row.id)}`;
          return (
            <linearGradient
              key={gradientId}
              id={gradientId}
              gradientUnits="userSpaceOnUse"
              x1="0"
              y1="0"
              x2={TREND_CHART_WIDTH}
              y2="0"
            >
              {buildTrendLineGradientStops(row.color, highlightX).map((stop, index) => (
                <stop
                  key={`${gradientId}-stop-${index}`}
                  offset={stop.offset}
                  stopColor={stop.color}
                />
              ))}
            </linearGradient>
          );
        })}
      </defs>
      {chartRows.map((row) => {
        const highlightX = hoveredLineHighlights.get(row.id);
        const gradientId = `trend-grad-${sanitizeSvgId(row.id)}`;
        const isHighlighted = highlightX !== undefined;

        return (
          <path
            key={row.id}
            className={`trend-line model-trend-line${isHighlighted ? " is-highlighted" : ""}`}
            d={row.path}
            style={{
              stroke: isHighlighted ? `url(#${gradientId})` : row.color,
            }}
          />
        );
      })}
    </svg>
  );
}
