"use client";

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type FocusEvent,
  type MouseEvent,
} from "react";
import { isDesktopFinePointer } from "@/shared/lib/hooks/useFloatingPanelScrollListeners";
import { useMobile760 } from "@/shared/lib/hooks/useMobile760";
import type {
  MultiSeriesTrendChartProps,
  TrendChartDot,
  TrendChartDotView,
  TrendDotCluster,
} from "@/shared/lib/trendChart/chartTypes";
import {
  TREND_PLOT_BOTTOM,
  TREND_PLOT_TOP,
  buildTrendChartRows,
  collectYValues,
} from "@/shared/lib/trendChart/buildTrendChartRows";
import {
  groupOverlappingTrendDots,
  trendDotKey,
} from "@/shared/lib/trendChart/dotClustering";
import {
  TREND_CHART_WIDTH,
  buildAdaptiveValueScale,
  computeClusterStripLeft,
  formatTrendNumber,
} from "@/shared/lib/trendChart/math";
import { formatTrendPointPeriod } from "@/shared/lib/trendChart/periodLabels";

export function useMultiSeriesTrendChart({
  labels,
  series,
  period,
  compactAxisLabels = false,
  showYAxisLabels = true,
  pointEdgeInsetPercent = 0,
  formatAxisValue = formatTrendNumber,
  getDotExtraLines,
}: MultiSeriesTrendChartProps) {
  const isMobile = useMobile760();
  const [hoveredClusterId, setHoveredClusterId] = useState<string | null>(null);
  const [hoveredDotKey, setHoveredDotKey] = useState<string | null>(null);
  const [clusterStripAnchor, setClusterStripAnchor] = useState<{
    left?: number;
    bottom: number;
  } | null>(null);
  const [clusterAnchor, setClusterAnchor] = useState<{ dotX: number } | null>(null);
  const clusterStripRef = useRef<HTMLDivElement>(null);
  const chartWrapRef = useRef<HTMLDivElement>(null);
  const dotClustersRef = useRef<TrendDotCluster[]>([]);
  const [chartSizePx, setChartSizePx] = useState({ width: 0, height: 0 });

  const chartHeight = TREND_PLOT_BOTTOM - TREND_PLOT_TOP;
  const valueScale = buildAdaptiveValueScale(collectYValues(series, labels.length));
  const midValue = valueScale.min + valueScale.span / 2;
  const gridRows = [
    { y: TREND_PLOT_TOP, label: formatAxisValue(valueScale.max, valueScale.max) },
    { y: (TREND_PLOT_TOP + TREND_PLOT_BOTTOM) / 2, label: formatAxisValue(midValue, valueScale.max) },
    { y: TREND_PLOT_BOTTOM, label: formatAxisValue(valueScale.min, valueScale.max) },
  ];

  const chartRows = buildTrendChartRows({
    labels,
    series,
    period,
    pointEdgeInsetPercent,
    valueScale,
    getDotExtraLines,
  });

  useLayoutEffect(() => {
    const node = chartWrapRef.current;
    if (!node) return;

    const updateSize = () => {
      const width = node.clientWidth;
      const height = node.clientHeight;
      setChartSizePx((prev) =>
        prev.width === width && prev.height === height ? prev : { width, height },
      );
    };
    updateSize();

    const observer = new ResizeObserver(updateSize);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const { chartDots, dotClusters } = useMemo(() => {
    const flatDots: TrendChartDot[] = chartRows.flatMap((row) =>
      row.dots.map((dot, index) => ({
        seriesId: row.id,
        seriesLabel: row.label,
        color: row.color,
        x: dot.x,
        y: dot.y,
        value: dot.value,
        label: dot.label ?? labels[index],
        pointIndex: dot.pointIndex ?? index,
        periodLabel: dot.periodLabel ?? formatTrendPointPeriod(period, index, labels.length),
        extraLines: dot.extraLines,
      })),
    );
    const clusters = groupOverlappingTrendDots(
      flatDots,
      chartSizePx.width,
      chartSizePx.height,
    );
    const clusterSizeById = new Map(clusters.map((cluster) => [cluster.id, cluster.dots.length]));
    const clusterIdByKey = new Map<string, string>();
    clusters.forEach((cluster) => {
      cluster.dots.forEach((dot) => clusterIdByKey.set(trendDotKey(dot), cluster.id));
    });

    return {
      dotClusters: clusters,
      chartDots: flatDots.map((dot) => {
        const clusterId = clusterIdByKey.get(trendDotKey(dot)) ?? "";
        return {
          ...dot,
          clusterId,
          clusterSize: clusterSizeById.get(clusterId) ?? 1,
        } satisfies TrendChartDotView;
      }),
    };
  }, [chartRows, labels, period, chartSizePx.height, chartSizePx.width]);

  dotClustersRef.current = dotClusters;

  const clearTrendHover = useCallback(() => {
    setHoveredClusterId(null);
    setHoveredDotKey(null);
    setClusterAnchor(null);
    setClusterStripAnchor(null);
    const wrap = chartWrapRef.current;
    const active = document.activeElement;
    if (active instanceof HTMLElement && wrap?.contains(active)) {
      active.blur();
    }
  }, []);

  const activateDot = useCallback((dot: TrendChartDotView, rectTop: number) => {
    setHoveredClusterId(dot.clusterId);
    setHoveredDotKey(trendDotKey(dot));
    setClusterAnchor({ dotX: dot.x });
    setClusterStripAnchor({
      bottom: Math.round(window.innerHeight - rectTop + 10),
    });
  }, []);

  const onDotMouseEnter = useCallback(
    (dot: TrendChartDotView, event: MouseEvent<HTMLButtonElement>) => {
      const rect = event.currentTarget.getBoundingClientRect();
      activateDot(dot, rect.top);
    },
    [activateDot],
  );

  const onDotFocus = useCallback(
    (dot: TrendChartDotView, event: FocusEvent<HTMLButtonElement>) => {
      const rect = event.currentTarget.getBoundingClientRect();
      activateDot(dot, rect.top);
    },
    [activateDot],
  );

  useEffect(() => {
    if (!isMobile || !hoveredClusterId) return;

    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      const wrap = chartWrapRef.current;
      const dotEl =
        target instanceof Element ? target.closest<HTMLButtonElement>(".trend-html-dot") : null;

      if (dotEl && wrap?.contains(dotEl)) {
        const dotKey = dotEl.getAttribute("data-trend-dot-key");
        const cluster = dotClustersRef.current.find((item) =>
          item.dots.some((dot) => trendDotKey(dot) === dotKey),
        );
        if (cluster?.id === hoveredClusterId) {
          clearTrendHover();
          event.preventDefault();
          event.stopPropagation();
        }
        return;
      }

      if (clusterStripRef.current?.contains(target)) return;

      clearTrendHover();
    };

    document.addEventListener("pointerdown", onPointerDown, true);
    return () => document.removeEventListener("pointerdown", onPointerDown, true);
  }, [isMobile, hoveredClusterId, clearTrendHover]);

  useEffect(() => {
    if (isMobile || !hoveredClusterId) return;
    if (!isDesktopFinePointer()) return;
    const onScroll = () => clearTrendHover();
    window.addEventListener("scroll", onScroll, true);
    return () => window.removeEventListener("scroll", onScroll, true);
  }, [isMobile, hoveredClusterId, clearTrendHover]);

  const hoveredCluster = useMemo(
    () => dotClusters.find((cluster) => cluster.id === hoveredClusterId) ?? null,
    [dotClusters, hoveredClusterId],
  );

  const clusterStripSyncKey =
    hoveredClusterId && hoveredDotKey && clusterAnchor
      ? `${hoveredClusterId}\u0000${hoveredDotKey}\u0000${clusterAnchor.dotX}\u0000${chartSizePx.width}\u0000${chartSizePx.height}\u0000${hoveredCluster?.dots.length ?? 0}`
      : "";

  const hoveredLineHighlights = useMemo(() => {
    if (!hoveredCluster) return new Map<string, number>();
    const highlights = new Map<string, number>();
    hoveredCluster.dots.forEach((dot) => {
      highlights.set(dot.seriesId, (dot.x / 100) * TREND_CHART_WIDTH);
    });
    return highlights;
  }, [hoveredCluster]);

  useLayoutEffect(() => {
    if (!clusterStripSyncKey) {
      setClusterStripAnchor((prev) => (prev === null ? prev : null));
      return;
    }

    const [clusterId, dotKey] = clusterStripSyncKey.split("\u0000");
    const clusterSize =
      dotClustersRef.current.find((item) => item.id === clusterId)?.dots.length ?? 0;
    if (clusterSize < 2) {
      setClusterStripAnchor((prev) => (prev === null ? prev : null));
      return;
    }

    const wrap = chartWrapRef.current;
    if (!wrap) {
      setClusterStripAnchor((prev) => (prev === null ? prev : null));
      return;
    }

    const anchor = wrap.querySelector<HTMLButtonElement>(
      `[data-trend-dot-key="${CSS.escape(dotKey)}"]`,
    );
    if (!anchor) {
      setClusterStripAnchor((prev) => (prev === null ? prev : null));
      return;
    }

    const update = () => {
      const anchorRect = anchor.getBoundingClientRect();
      const strip = clusterStripRef.current;
      if (!strip) return;

      const anchorCenterX = anchorRect.left + anchorRect.width / 2;
      const dotX = clusterAnchor?.dotX ?? 50;
      const bottom = Math.round(window.innerHeight - anchorRect.top + 10);
      const stripWidth = strip.offsetWidth;
      if (stripWidth === 0) {
        requestAnimationFrame(update);
        return;
      }

      const next = {
        left: computeClusterStripLeft(anchorCenterX, stripWidth, dotX),
        bottom,
      };
      setClusterStripAnchor((prev) =>
        prev && prev.left === next.left && prev.bottom === next.bottom ? prev : next,
      );
    };

    update();
    const strip = clusterStripRef.current;
    const resizeObserver =
      strip &&
      new ResizeObserver(() => {
        update();
      });
    if (strip && resizeObserver) resizeObserver.observe(strip);
    const onResize = () => update();
    const onScroll = () => {
      if (isDesktopFinePointer()) {
        clearTrendHover();
        return;
      }
      update();
    };
    window.addEventListener("resize", onResize);
    window.addEventListener("scroll", onScroll, true);

    return () => {
      resizeObserver?.disconnect();
      window.removeEventListener("resize", onResize);
      window.removeEventListener("scroll", onScroll, true);
    };
  }, [clusterStripSyncKey, clusterAnchor, clearTrendHover]);

  return {
    isMobile,
    showYAxisLabels,
    compactAxisLabels,
    labels,
    series,
    period,
    pointEdgeInsetPercent,
    chartWrapRef,
    clusterStripRef,
    gridRows,
    chartRows,
    chartDots,
    hoveredCluster,
    hoveredClusterId,
    clusterAnchor,
    clusterStripAnchor,
    hoveredLineHighlights,
    clearTrendHover,
    onDotMouseEnter,
    onDotFocus,
    setHoveredClusterId,
    setHoveredDotKey,
    setClusterAnchor,
    setClusterStripAnchor,
  };
}
