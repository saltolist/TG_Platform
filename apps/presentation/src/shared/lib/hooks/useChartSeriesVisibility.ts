"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

export function useChartSeriesVisibility(seriesIds: string[]) {
  const [visibleById, setVisibleById] = useState<Record<string, boolean>>({});

  useEffect(() => {
    setVisibleById((prev) => {
      const next = { ...prev };
      let changed = false;
      for (const id of seriesIds) {
        if (next[id] === undefined) {
          next[id] = true;
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [seriesIds]);

  const isVisible = useCallback(
    (id: string) => visibleById[id] !== false,
    [visibleById],
  );

  const setVisible = useCallback((id: string, visible: boolean) => {
    setVisibleById((prev) => {
      if (prev[id] === visible) return prev;
      return { ...prev, [id]: visible };
    });
  }, []);

  const filterSeries = useCallback(
    <T extends { id: string }>(series: T[]) => series.filter((row) => isVisible(row.id)),
    [isVisible],
  );

  const visibleCount = useMemo(
    () => seriesIds.filter((id) => isVisible(id)).length,
    [isVisible, seriesIds],
  );

  return { isVisible, setVisible, filterSeries, visibleCount };
}
