"use client";

import { useEffect, useState } from "react";
import {
  DEFAULT_PLACEHOLDER,
  NARROW_PLACEHOLDER,
} from "@/widgets/composer/model/editor/constants";

export function useComposerLayout(placeholder?: string) {
  const [narrowComposer, setNarrowComposer] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 760px)");
    const sync = () => setNarrowComposer(mq.matches);
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);

  const effectivePlaceholder =
    placeholder || (narrowComposer ? NARROW_PLACEHOLDER : DEFAULT_PLACEHOLDER);

  return { narrowComposer, effectivePlaceholder };
}
