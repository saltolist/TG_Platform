"use client";

import { useState, type ChangeEvent } from "react";
import { isApiKeyPreview } from "@/shared/lib/profile/maskedApiKey";

/** Local edit state for a secret field backed by a preview token from the server. */
export function useSecretFieldEdit(storedValue: string, onStoredChange: (value: string) => void) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");

  const displayValue = editing ? draft : storedValue;

  return {
    displayValue,
    inputProps: {
      value: displayValue,
      onFocus: () => {
        setEditing(true);
        setDraft(isApiKeyPreview(storedValue) ? "" : storedValue);
      },
      onChange: (e: ChangeEvent<HTMLInputElement>) => {
        const next = e.target.value;
        setDraft(next);
        onStoredChange(next);
      },
      onBlur: () => {
        setEditing(false);
        if (isApiKeyPreview(storedValue) && !draft.trim()) {
          onStoredChange(storedValue);
        }
      },
    },
  };
}
