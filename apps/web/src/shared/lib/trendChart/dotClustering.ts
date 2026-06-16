import {
  TREND_CHART_HEIGHT_PX,
  TREND_DOT_CLUSTER_FALLBACK_WIDTH_PX,
  TREND_DOT_CORE_DIAMETER_PX,
} from "@/shared/lib/trendChart/math";
import type { TrendChartDot, TrendDotCluster } from "@/shared/lib/trendChart/chartTypes";

export function trendDotKey(dot: Pick<TrendChartDot, "seriesId" | "label">) {
  return `${dot.seriesId}:${dot.label}`;
}

export function trendDotCenterDistancePx(
  a: { x: number; y: number },
  b: { x: number; y: number },
  chartWidthPx: number,
  chartHeightPx: number,
) {
  const widthPx = chartWidthPx > 0 ? chartWidthPx : TREND_DOT_CLUSTER_FALLBACK_WIDTH_PX;
  const heightPx = chartHeightPx > 0 ? chartHeightPx : TREND_CHART_HEIGHT_PX;
  const dxPx = (Math.abs(b.x - a.x) / 100) * widthPx;
  const dyPx = (Math.abs(b.y - a.y) / 100) * heightPx;
  return Math.hypot(dxPx, dyPx);
}

export function groupOverlappingTrendDots(
  dots: TrendChartDot[],
  chartWidthPx: number,
  chartHeightPx: number,
): TrendDotCluster[] {
  if (dots.length === 0) return [];

  const used = new Set<number>();
  const clusters: TrendChartDot[][] = [];

  for (let i = 0; i < dots.length; i += 1) {
    if (used.has(i)) continue;

    const cluster: TrendChartDot[] = [dots[i]];
    used.add(i);

    let grew = true;
    while (grew) {
      grew = false;
      for (let j = 0; j < dots.length; j += 1) {
        if (used.has(j)) continue;
        const touchesCluster = cluster.some(
          (member) =>
            trendDotCenterDistancePx(member, dots[j], chartWidthPx, chartHeightPx) <=
            TREND_DOT_CORE_DIAMETER_PX,
        );
        if (!touchesCluster) continue;
        cluster.push(dots[j]);
        used.add(j);
        grew = true;
      }
    }

    clusters.push(cluster);
  }

  return clusters.map((clusterDots, index) => {
    const xs = clusterDots.map((dot) => dot.x);
    const ys = clusterDots.map((dot) => dot.y);

    return {
      id: `cluster-${index}-${clusterDots.map((dot) => `${dot.seriesId}:${dot.label}`).join("|")}`,
      dots: clusterDots,
      x: xs.reduce((sum, value) => sum + value, 0) / clusterDots.length,
      y: ys.reduce((sum, value) => sum + value, 0) / clusterDots.length,
    };
  });
}

export function shouldClearTrendDotHover(relatedTarget: EventTarget | null, currentTarget: HTMLElement) {
  const chartWrap = currentTarget.closest(".trend-chart-wrap");
  if (relatedTarget instanceof Node && chartWrap?.contains(relatedTarget)) {
    if (relatedTarget instanceof Element && relatedTarget.closest(".trend-html-dot")) {
      return false;
    }
  }
  return true;
}
