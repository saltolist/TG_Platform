export type AnalyticsTopPostRow = {
  id: string;
  title: string;
  subscribers: number;
  reactions: number;
  views: number;
  comments: number;
  reposts: number;
  er: number;
};

export const ANALYTICS_HEATMAP_ROWS = [
  { day: "Пн", values: [1, 2, 3, 4, 3] },
  { day: "Вт", values: [1, 3, 4, 5, 4] },
  { day: "Ср", values: [2, 2, 3, 4, 5] },
  { day: "Чт", values: [1, 3, 4, 4, 3] },
  { day: "Пт", values: [1, 2, 3, 5, 4] },
  { day: "Сб", values: [2, 3, 3, 4, 3] },
  { day: "Вс", values: [2, 3, 4, 4, 5] },
] as const;

export const ANALYTICS_HEATMAP_HOURS = ["09", "12", "15", "18", "21"] as const;
