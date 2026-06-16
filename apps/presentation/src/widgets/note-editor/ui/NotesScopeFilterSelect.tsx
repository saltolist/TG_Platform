"use client";

import { FilterTabSelect } from "@/shared/ui/filter-tab-select";
import type { NoteScope } from "@/shared/types";

const OPTIONS: { value: NoteScope; label: string }[] = [
  { value: "all", label: "Глобальные / локальные" },
  { value: "global", label: "Только глобальные" },
  { value: "local", label: "Только локальные" },
];

type Props = {
  value: NoteScope;
  onChange: (value: NoteScope) => void;
};

export default function NotesScopeFilterSelect({ value, onChange }: Props) {
  return (
    <FilterTabSelect
      className="notes-filter-tab-select"
      value={value}
      options={OPTIONS}
      onChange={onChange}
      ariaLabel="Область заметок"
    />
  );
}
