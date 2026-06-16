"use client";

import {
  AiModelsBlock,
  SystemPromptBlock,
  TelegramBlock,
  ThemeBlock,
  UserBlock,
} from "@/widgets/profile-settings";

type Props = {
  active: boolean;
  settingsTabActive: boolean;
};

export default function ProfileSettingsPanel({ active, settingsTabActive }: Props) {
  return (
    <div className={`profile-panel profile-panel--settings${active ? " active" : ""}`}>
      <ThemeBlock />
      <UserBlock />
      <AiModelsBlock />
      <SystemPromptBlock active={settingsTabActive} />
      <TelegramBlock active={settingsTabActive} />
    </div>
  );
}
