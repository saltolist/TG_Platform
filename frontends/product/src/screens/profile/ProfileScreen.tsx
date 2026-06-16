"use client";

import { ChannelTab } from "@/widgets/profile-settings";
import ProfileAnalyticsPanel from "@/screens/profile/ui/ProfileAnalyticsPanel";
import ProfileScreenHeader from "@/screens/profile/ui/ProfileScreenHeader";
import ProfileSettingsPanel from "@/screens/profile/ui/ProfileSettingsPanel";
import { useProfileScreen } from "@/screens/profile/model/useProfileScreen";

export function ProfileScreen() {
  const { data, ui, actions } = useProfileScreen();

  return (
    <>
      <ProfileScreenHeader data={data} ui={ui} actions={actions} />
      <div className="profile-page">
        <div className="profile-scroll-inner">
          <ChannelTab active={data.channelTabActive} />
          <ProfileSettingsPanel active={data.tab === 0} settingsTabActive={data.settingsTabActive} />
          <ProfileAnalyticsPanel
            active={data.tab === 2}
            period={data.platformPeriod}
            onPeriodChange={actions.setPlatformPeriod}
            periodInHeader={ui.platformPeriodInHeader}
          />
        </div>
      </div>
    </>
  );
}
