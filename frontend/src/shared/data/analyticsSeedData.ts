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

export const ANALYTICS_TOP_POSTS_SEED: AnalyticsTopPostRow[] = [
  {
    id: "1",
    title: "Синдром чистого листа с деньгами",
    subscribers: 51,
    reactions: 917,
    views: 5100,
    comments: 48,
    reposts: 23,
    er: 6.4,
  },
  {
    id: "2",
    title: "Почему ИИС — не страшно",
    subscribers: 34,
    reactions: 612,
    views: 4200,
    comments: 31,
    reposts: 18,
    er: 5.1,
  },
  {
    id: "5",
    title: "Личный опыт с ETF",
    subscribers: 28,
    reactions: 488,
    views: 3800,
    comments: 22,
    reposts: 14,
    er: 5.8,
  },
];

export const ANALYTICS_HEATMAP_HOURS = ["09", "12", "15", "18", "21"] as const;
