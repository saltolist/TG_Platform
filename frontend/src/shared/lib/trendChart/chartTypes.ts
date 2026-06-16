export type TrendSeriesRow = {
  id: string;
  label: string;
  color: string;
  values: number[];
  yValues?: number[];
  /** Накопительное значение на момент перед первой точкой графика (пред. день/час). */
  priorCumulative?: number;
};

export type TrendChartDot = {
  seriesId: string;
  seriesLabel: string;
  color: string;
  x: number;
  y: number;
  value: number;
  label: string;
  pointIndex: number;
  periodLabel: string;
  extraLines: string[];
};

export type TrendDotCluster = {
  id: string;
  dots: TrendChartDot[];
  x: number;
  y: number;
};

export type TrendChartDotView = TrendChartDot & {
  clusterId: string;
  clusterSize: number;
};

export type TrendChartRow = TrendSeriesRow & {
  path: string;
  dots: {
    x: number;
    y: number;
    value: number;
    label: string;
    pointIndex: number;
    periodLabel: string;
    extraLines: string[];
  }[];
};

export type MultiSeriesTrendChartProps = {
  labels: string[];
  series: TrendSeriesRow[];
  period: number;
  title: string;
  compactAxisLabels?: boolean;
  showYAxisLabels?: boolean;
  /** Доля отступа крайних точек от края plot (%); на десктопе 0. */
  pointEdgeInsetPercent?: number;
  formatAxisValue?: (value: number, scaleMax: number) => string;
  getDotPrimaryLine: (row: TrendSeriesRow, value: number, pointIndex: number) => string;
  getDotGrowthBadge?: (row: TrendSeriesRow, value: number, pointIndex: number) => string;
  getDotRangeFromStartLine?: (row: TrendSeriesRow, value: number, pointIndex: number) => string;
  getDotPercentGrowthLine?: (row: TrendSeriesRow, value: number, pointIndex: number) => string;
  getDotExtraLines?: (row: TrendSeriesRow, value: number, pointIndex: number) => string[];
};
