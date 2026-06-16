"use client";

import { PageHeader, PageHeaderSelect } from "@/widgets/page-header";
import { PLATFORM_ANALYTICS_PERIODS } from "@/shared/lib/platformAnalyticsPeriods";
import { PROFILE_TABS } from "@/shared/lib/profileTabs";
import { useScreenBack } from "@/widgets/app-shell/model/useScreenBack";
import type { ProfileScreenState } from "@/screens/profile/model/useProfileScreen";

type Props = {
  data: Pick<ProfileScreenState["data"], "tab" | "platformPeriod">;
  ui: Pick<
    ProfileScreenState["ui"],
    "isMobile" | "isCompactHeader" | "platformPeriodInHeader" | "profileTabSelectProps"
  >;
  actions: Pick<ProfileScreenState["actions"], "setPlatformPeriod" | "switchTab">;
};

function ProfileTabToolbar({
  tab,
  onSwitchTab,
}: {
  tab: number;
  onSwitchTab: (index: number) => void;
}) {
  return (
    <div className="page-header-profile-tabs" role="tablist" aria-label="Раздел профиля">
      {PROFILE_TABS.map((label, i) => (
        <button
          key={label}
          type="button"
          role="tab"
          aria-selected={i === tab}
          className={`period-tab${i === tab ? " active" : ""}`}
          onClick={() => onSwitchTab(i)}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

export default function ProfileScreenHeader({ data, ui, actions }: Props) {
  const onBack = useScreenBack();
  const { tab, platformPeriod } = data;
  const { isCompactHeader, platformPeriodInHeader, profileTabSelectProps } = ui;
  const { setPlatformPeriod, switchTab } = actions;

  const platformPeriodHeaderPicker = platformPeriodInHeader ? (
    <PageHeaderSelect
      ariaLabel="Период"
      chevron="down"
      className="page-header-select--profile-tabs"
      value={String(platformPeriod)}
      options={PLATFORM_ANALYTICS_PERIODS.map((item, index) => ({
        value: String(index),
        label: item.label,
      }))}
      onChange={(id) => setPlatformPeriod(Number(id))}
    />
  ) : null;

  const tabToolbar = <ProfileTabToolbar tab={tab} onSwitchTab={switchTab} />;

  return (
    <PageHeader
      title="Профиль канала"
      onBack={onBack}
      center={
        isCompactHeader ? undefined : (
          <div className="page-header-toolbar--desktop page-header-profile-center-toolbar">
            {tabToolbar}
            {platformPeriodHeaderPicker}
          </div>
        )
      }
      mobileSelect={
        isCompactHeader ? (
          <div className="page-header-profile-trailing-toolbar">
            <PageHeaderSelect
              {...profileTabSelectProps}
              className="page-header-select--profile-tabs"
            />
            {platformPeriodHeaderPicker}
          </div>
        ) : undefined
      }
    />
  );
}
