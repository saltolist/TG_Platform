export const TREND_CHART_WIDTH = 264;
export const TREND_CHART_HEIGHT_PX = 493;
export const MOBILE_TREND_CHART_HEIGHT_PX = Math.round(TREND_CHART_HEIGHT_PX / 2);
export const TREND_DOT_CORE_DIAMETER_PX = 7.5;
export const TREND_DOT_CLUSTER_FALLBACK_WIDTH_PX = 720;

export const TREND_CLUSTER_STRIP_MARGIN_PX = 12;
export const TREND_CLUSTER_STRIP_MAX_COLUMNS = 5;
/** Мобильная версия: не больше двух карточек в ряд. */
export const TREND_CLUSTER_STRIP_MAX_COLUMNS_MOBILE = 2;
export const TREND_CLUSTER_LEFT_EDGE_PERCENT = 20;
export const TREND_CLUSTER_RIGHT_EDGE_PERCENT = 80;

export function getClusterStripColumnCount(
  cardCount: number,
  maxColumns: number = TREND_CLUSTER_STRIP_MAX_COLUMNS,
) {
  return Math.min(Math.max(cardCount, 1), maxColumns);
}

export function computeClusterStripLeft(pointerX: number, stripWidth: number, dotXPercent: number) {
  const margin = TREND_CLUSTER_STRIP_MARGIN_PX;
  const minLeft = margin;
  const maxLeft = Math.max(minLeft, window.innerWidth - stripWidth - margin);

  let anchorOffset: number;
  if (dotXPercent >= TREND_CLUSTER_RIGHT_EDGE_PERCENT) {
    anchorOffset = stripWidth;
  } else if (dotXPercent <= TREND_CLUSTER_LEFT_EDGE_PERCENT) {
    anchorOffset = 0;
  } else {
    anchorOffset = stripWidth / 2;
  }

  return Math.round(Math.max(minLeft, Math.min(maxLeft, pointerX - anchorOffset)));
}

export function sanitizeSvgId(value: string) {
  return value.replace(/[^a-zA-Z0-9_-]/g, "_");
}

export function darkenHex(hex: string, mix = 0.18) {
  const normalized = hex.trim();
  if (!normalized.startsWith("#")) return hex;
  const raw = normalized.slice(1);
  const full =
    raw.length === 3 ? raw.split("").map((channel) => channel + channel).join("") : raw;
  if (full.length !== 6) return hex;

  const channels = [0, 2, 4].map((offset) => parseInt(full.slice(offset, offset + 2), 16));
  const mixChannel = (channel: number) => Math.round(channel * (1 - mix));
  return `rgb(${mixChannel(channels[0])}, ${mixChannel(channels[1])}, ${mixChannel(channels[2])})`;
}

export function buildTrendLineGradientStops(baseColor: string, highlightX: number) {
  const darkColor = darkenHex(baseColor);
  const center = Math.max(0, Math.min(1, highlightX / TREND_CHART_WIDTH));
  const offset = (value: number) => `${(value * 100).toFixed(2)}%`;

  if (center <= 0.0001) {
    return [
      { offset: offset(0), color: darkColor },
      { offset: offset(1), color: baseColor },
    ];
  }

  if (center >= 0.9999) {
    return [
      { offset: offset(0), color: baseColor },
      { offset: offset(1), color: darkColor },
    ];
  }

  return [
    { offset: offset(0), color: baseColor },
    { offset: offset(center), color: darkColor },
    { offset: offset(1), color: baseColor },
  ];
}

function niceCeil(value: number) {
  if (!Number.isFinite(value) || value <= 0) return 0;
  const exponent = Math.floor(Math.log10(value));
  const magnitude = 10 ** exponent;
  const fraction = value / magnitude;
  const niceFraction = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10;
  return niceFraction * magnitude;
}

/** «Красивый» потолок шкалы без скачка на следующий порядок (100 → 200). */
function cappedNiceCeil(rawMax: number, dataMax: number, pad: number) {
  const ceiling = dataMax + Math.max(pad * 1.15, dataMax * 0.1);
  const nice = niceCeil(rawMax);
  if (nice <= 0 || !Number.isFinite(nice)) return rawMax;
  if (nice <= ceiling) return nice;
  return Math.max(rawMax, ceiling);
}

export function buildAdaptiveValueScale(values: number[]) {
  const finite = values.filter((value) => Number.isFinite(value));
  const dataMax = finite.length > 0 ? Math.max(...finite) : 0;
  const dataMin = finite.length > 0 ? Math.min(...finite) : 0;

  if (finite.length === 0 || (dataMax <= 0 && dataMin >= 0)) {
    return { min: 0, max: 0.01, span: 0.01 };
  }

  const spread = Math.max(0, dataMax - dataMin);
  const relativeSpread = dataMax > 0 ? spread / dataMax : 0;

  const pad = Math.max(
    spread * (relativeSpread < 0.12 ? 0.12 : 0.08),
    dataMax * 0.05,
    spread * 0.04,
    0.000_001,
  );

  const rawMax = dataMax + pad;
  const axisTop = cappedNiceCeil(rawMax, dataMax, pad);

  // Ноль на оси, если все значения неотрицательны и близки к нулю; отрицательный прирост — шкала через 0.
  const anchorAtZero = dataMin >= 0 && (spread <= 0 || dataMin <= dataMax * 0.12);
  const min = anchorAtZero
    ? 0
    : dataMin < 0
      ? dataMin - pad * 0.5
      : Math.max(0, dataMin - pad * 0.5);
  const top = Math.max(axisTop, rawMax);
  const span = Math.max(top - min, pad, dataMax * 0.03);

  return { min, max: min + span, span };
}

export function valueToChartY(
  value: number,
  scale: { min: number; span: number },
  chartBottom: number,
  chartHeight: number,
) {
  if (scale.span <= 0) return chartBottom;
  const normalized = (value - scale.min) / scale.span;
  return chartBottom - Math.min(1, Math.max(0, normalized)) * chartHeight;
}

export function buildSmoothPath(points: { x: number; y: number }[]) {
  if (points.length === 0) return "";
  if (points.length === 1) return `M ${points[0].x.toFixed(1)} ${points[0].y.toFixed(1)}`;

  return points.slice(1).reduce((path, point, i) => {
    const prev = points[i];
    const controlOffset = (point.x - prev.x) * 0.45;
    const c1x = prev.x + controlOffset;
    const c2x = point.x - controlOffset;

    return `${path} C ${c1x.toFixed(1)} ${prev.y.toFixed(1)}, ${c2x.toFixed(1)} ${point.y.toFixed(1)}, ${point.x.toFixed(1)} ${point.y.toFixed(1)}`;
  }, `M ${points[0].x.toFixed(1)} ${points[0].y.toFixed(1)}`);
}

export function formatTrendNumber(value: number, scaleMax: number) {
  const absMax = Math.max(scaleMax, Math.abs(value));
  if (absMax >= 1_000_000) {
    return new Intl.NumberFormat("ru-RU", {
      notation: "compact",
      maximumFractionDigits: 1,
    }).format(value);
  }
  if (absMax >= 10_000) return new Intl.NumberFormat("ru-RU").format(Math.round(value));
  if (absMax < 0.01) return value.toFixed(4);
  if (absMax < 1) return value.toFixed(2);
  if (absMax < 10) return value.toFixed(1);
  return new Intl.NumberFormat("ru-RU").format(Math.round(value));
}

export function formatTrendDollar(value: number, scaleMax: number) {
  const absMax = Math.max(scaleMax, Math.abs(value));
  if (absMax < 0.001) return `$${value.toFixed(5)}`;
  if (absMax < 0.01) return `$${value.toFixed(4)}`;
  if (absMax < 0.1) return `$${value.toFixed(3)}`;
  if (absMax < 10) return `$${value.toFixed(2)}`;
  return `$${value.toFixed(2)}`;
}

export function formatNumber(value: number) {
  return new Intl.NumberFormat("ru-RU").format(value);
}

export function formatCompact(value: number) {
  return new Intl.NumberFormat("ru-RU", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

export function hashString(value: string) {
  return value.split("").reduce((hash, char) => {
    const nextHash = (hash << 5) - hash + char.charCodeAt(0);
    return nextHash >>> 0;
  }, 2166136261);
}

export function buildTrend(seed: number, total: number, pointCount = 7) {
  const weights = Array.from({ length: pointCount }, (_, i) => {
    const progress = pointCount === 1 ? 0 : i / (pointCount - 1);
    const weight = 0.72 + progress * 0.56;
    return weight + ((seed >> (i % 8)) % 5) * 0.035;
  });
  const weightTotal = weights.reduce((sum, weight) => sum + weight, 0);
  return weights.map((weight) => Math.max(1, Math.round((total * weight) / weightTotal)));
}
