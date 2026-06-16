"use client";

import { useEffect, useMemo, useState } from "react";

import { formatPostDateTime } from "@/shared/lib/helpers";

const MONTH_NAMES = [
  "Январь",
  "Февраль",
  "Март",
  "Апрель",
  "Май",
  "Июнь",
  "Июль",
  "Август",
  "Сентябрь",
  "Октябрь",
  "Ноябрь",
  "Декабрь",
];
const DAY_NAMES = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

type Props = {
  initialDate: Date;
  plannedDate?: Date | null;
  onClose: () => void;
  onConfirm: (value: string) => void;
};

export default function SchedulePickerModal({
  initialDate,
  plannedDate,
  onClose,
  onConfirm,
}: Props) {
  const today = new Date();
  const todayY = today.getFullYear();
  const todayM = today.getMonth();
  const todayD = today.getDate();

  const [viewYear, setViewYear] = useState(initialDate.getFullYear());
  const [viewMonth, setViewMonth] = useState(initialDate.getMonth());
  const [selDay, setSelDay] = useState(initialDate.getDate());
  const [selHours, setSelHours] = useState(initialDate.getHours());
  const [selMinutes, setSelMinutes] = useState(
    Math.round(initialDate.getMinutes() / 5) * 5 % 60,
  );

  useEffect(() => {
    setViewYear(initialDate.getFullYear());
    setViewMonth(initialDate.getMonth());
    setSelDay(initialDate.getDate());
    setSelHours(initialDate.getHours());
    setSelMinutes(Math.round(initialDate.getMinutes() / 5) * 5 % 60);
  }, [initialDate]);

  const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();
  const firstDayOfWeek = new Date(viewYear, viewMonth, 1).getDay();
  const firstColMon = (firstDayOfWeek + 6) % 7;

  const isPast = (d: number) => {
    if (viewYear !== todayY) return viewYear < todayY;
    if (viewMonth !== todayM) return viewMonth < todayM;
    return d < todayD;
  };
  const isSelected = (d: number) => d === selDay;
  const isPlanned = (d: number) =>
    plannedDate != null &&
    viewYear === plannedDate.getFullYear() &&
    viewMonth === plannedDate.getMonth() &&
    d === plannedDate.getDate();
  const canGoBack = !(viewYear === todayY && viewMonth === todayM);

  const goToPrevMonth = () => {
    let m = viewMonth - 1;
    let y = viewYear;
    if (m < 0) {
      m = 11;
      y--;
    }
    const max = new Date(y, m + 1, 0).getDate();
    setSelDay((d) => Math.min(d, max));
    setViewMonth(m);
    setViewYear(y);
  };

  const goToNextMonth = () => {
    let m = viewMonth + 1;
    let y = viewYear;
    if (m > 11) {
      m = 0;
      y++;
    }
    const max = new Date(y, m + 1, 0).getDate();
    setSelDay((d) => Math.min(d, max));
    setViewMonth(m);
    setViewYear(y);
  };

  const cells: (number | null)[] = [
    ...Array<null>(firstColMon).fill(null),
    ...Array.from({ length: daysInMonth }, (_, i) => i + 1),
  ];
  while (cells.length % 7 !== 0) cells.push(null);

  const stepHours = (delta: number) => setSelHours((h) => (h + delta + 24) % 24);
  const stepMinutes = (delta: number) => setSelMinutes((m) => (m + delta + 60) % 60);

  const selectedLabel = useMemo(
    () => formatPostDateTime(new Date(viewYear, viewMonth, selDay, selHours, selMinutes)),
    [viewYear, viewMonth, selDay, selHours, selMinutes],
  );

  const handleConfirm = () => {
    const mm = String(viewMonth + 1).padStart(2, "0");
    const dd = String(selDay).padStart(2, "0");
    const hh = String(selHours).padStart(2, "0");
    const mn = String(selMinutes).padStart(2, "0");
    onConfirm(`${viewYear}-${mm}-${dd}T${hh}:${mn}`);
  };

  return (
    <div className="schedule-modal-backdrop" onClick={onClose}>
      <div
        className="schedule-modal"
        role="dialog"
        aria-modal="true"
        aria-label="Запланировать публикацию"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="schedule-modal-title">Запланировать публикацию</div>
        <div className="schedule-modal-selected">{selectedLabel}</div>

        <div className="sched-cal">
          <div className="sched-cal-nav">
            <button
              type="button"
              className="sched-cal-nav-btn"
              onClick={goToPrevMonth}
              disabled={!canGoBack}
              aria-label="Предыдущий месяц"
            >
              ‹
            </button>
            <span className="sched-cal-month">
              {MONTH_NAMES[viewMonth]} {viewYear}
            </span>
            <button
              type="button"
              className="sched-cal-nav-btn"
              onClick={goToNextMonth}
              aria-label="Следующий месяц"
            >
              ›
            </button>
          </div>

          <div className="sched-cal-grid">
            {DAY_NAMES.map((name) => (
              <div key={name} className="sched-cal-dname">
                {name}
              </div>
            ))}
            {cells.map((d, i) =>
              d === null ? (
                <div key={`gap-${i}`} className="sched-cal-cell sched-cal-cell--empty" />
              ) : (
                <button
                  key={d}
                  type="button"
                  disabled={isPast(d)}
                  onClick={() => setSelDay(d)}
                  className={[
                    "sched-cal-cell",
                    isSelected(d) ? "sched-cal-cell--sel" : "",
                    isPlanned(d) ? "sched-cal-cell--planned" : "",
                    isPast(d) ? "sched-cal-cell--past" : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                >
                  {d}
                </button>
              ),
            )}
          </div>
        </div>

        <div className="sched-time">
          <span className="sched-time-label">Время публикации</span>
          <div className="sched-time-picker">
            <div className="sched-time-unit">
              <input
                className="sched-time-input"
                type="number"
                min={0}
                max={23}
                value={String(selHours).padStart(2, "0")}
                onChange={(e) => {
                  const v = parseInt(e.target.value, 10);
                  if (!Number.isNaN(v)) setSelHours(Math.max(0, Math.min(23, v)));
                }}
              />
              <div className="sched-time-arrows">
                <button type="button" className="sched-time-btn" onClick={() => stepHours(1)}>
                  ▲
                </button>
                <button type="button" className="sched-time-btn" onClick={() => stepHours(-1)}>
                  ▼
                </button>
              </div>
            </div>
            <span className="sched-time-colon">:</span>
            <div className="sched-time-unit">
              <input
                className="sched-time-input"
                type="number"
                min={0}
                max={59}
                value={String(selMinutes).padStart(2, "0")}
                onChange={(e) => {
                  const v = parseInt(e.target.value, 10);
                  if (!Number.isNaN(v)) setSelMinutes(Math.max(0, Math.min(59, v)));
                }}
              />
              <div className="sched-time-arrows">
                <button type="button" className="sched-time-btn" onClick={() => stepMinutes(5)}>
                  ▲
                </button>
                <button type="button" className="sched-time-btn" onClick={() => stepMinutes(-5)}>
                  ▼
                </button>
              </div>
            </div>
          </div>
        </div>

        <div className="schedule-modal-actions msg-user-edit-bar">
          <button type="button" className="btn btn-primary post-edit-btn" onClick={handleConfirm}>
            Запланировать
          </button>
          <button type="button" className="btn btn-ghost post-edit-btn" onClick={onClose}>
            Отмена
          </button>
        </div>
      </div>
    </div>
  );
}
