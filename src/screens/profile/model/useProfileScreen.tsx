"use client";

import { useCallback, useMemo, useState } from "react";
import { useNavigation } from "@/app/model/store";
import { useUiStore } from "@/app/model/store";
import { flushAiModelsAutosave } from "@/shared/lib/profile/aiModelsAutosave";
import { useCompactHeader1000 } from "@/shared/lib/hooks/useCompactHeader1000";
import { useMobile760 } from "@/shared/lib/hooks/useMobile760";
import { confirmDialog } from "@/shared/ui/dialog";
import { usePageHeaderLe650 } from "@/widgets/page-header";
import { PROFILE_TABS } from "@/shared/lib/profileTabs";

export function useProfileScreen() {
  const [tab, setTab] = useState(0);
  const [platformPeriod, setPlatformPeriod] = useState(2);
  const { screen, discardProfileEdits } = useNavigation();
  const profileScreenActive = screen === "profile";
  const isMobile = useMobile760();
  const isCompactHeader = useCompactHeader1000();
  const isHeaderLe650 = usePageHeaderLe650();
  const platformPeriodInHeader = tab === 2 && !isMobile && isHeaderLe650;
  const settingsTabActive = tab === 0 && profileScreenActive;
  const channelTabActive = tab === 1 && profileScreenActive;

  const switchTab = useCallback(
    async (next: number) => {
      await flushAiModelsAutosave();
      const dirtyMap = useUiStore.getState().dirtyMap;
      const settingsDirty =
        dirtyMap["profile-ai"] || dirtyMap["profile-prompt"] || dirtyMap["profile-telegram"];
      if (tab === 0 && next !== 0 && settingsDirty) {
        const ok = await confirmDialog({
          message: "Есть несохранённые изменения в настройках профиля. Перейти без сохранения?",
          confirmLabel: "Перейти",
          destructive: true,
        });
        if (!ok) return;
        discardProfileEdits();
      }
      if (tab === 1 && next !== 1 && dirtyMap["profile-channel"]) {
        const ok = await confirmDialog({
          message: "Есть несохранённые изменения в профиле канала. Перейти без сохранения?",
          confirmLabel: "Перейти",
          destructive: true,
        });
        if (!ok) return;
        discardProfileEdits();
      }
      setTab(next);
    },
    [discardProfileEdits, tab],
  );

  const profileTabSelectProps = useMemo(
    () => ({
      ariaLabel: "Раздел профиля",
      value: String(tab),
      options: PROFILE_TABS.map((label, i) => ({ value: String(i), label })),
      onChange: (v: string) => {
        void switchTab(Number(v));
      },
    }),
    [switchTab, tab],
  );

  return {
    data: {
      tab,
      platformPeriod,
      settingsTabActive,
      channelTabActive,
    },
    ui: {
      isMobile,
      isCompactHeader,
      platformPeriodInHeader,
      profileTabSelectProps,
    },
    actions: {
      setPlatformPeriod,
      switchTab,
    },
  };
}

export type ProfileScreenState = ReturnType<typeof useProfileScreen>;
