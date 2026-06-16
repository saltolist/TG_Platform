"use client";

import { useRef } from "react";
import ProfileSyncRow from "@/widgets/profile-settings/ui/ProfileSyncRow";
import { Area, ChannelSubsection } from "@/widgets/profile-settings/ui/channel/ChannelFormPrimitives";
import type { ChannelProfileConfig } from "@/shared/types";
import { useModSaveUndo } from "@/shared/lib/hooks/useModSaveUndo";

type Props = {
  active: boolean;
  cfg: ChannelProfileConfig;
  channelProfileDirty: boolean;
  onUpdateGroup: <K extends keyof ChannelProfileConfig>(
    group: K,
    patch: Partial<ChannelProfileConfig[K]>,
  ) => void;
  onSave: () => void;
  onReset: () => void;
};

export default function ChannelProfileSection({
  active,
  cfg,
  channelProfileDirty,
  onUpdateGroup,
  onSave,
  onReset,
}: Props) {
  const scopeRef = useRef<HTMLDivElement | null>(null);
  useModSaveUndo({ active, dirty: channelProfileDirty, onSave, scopeRef });

  return (
    <div className="profile-section profile-channel-combined-section" ref={scopeRef}>
      <ChannelSubsection title="Ядро канала">
        <div className="profile-grid">
          <ProfileSyncRow active={active} syncKey={`${cfg.core.topic}\u0000${cfg.core.angle}`}>
            <Area
              active={active}
              label="О чём канал"
              value={cfg.core.topic}
              onChange={(topic) => onUpdateGroup("core", { topic })}
            />
            <Area
              active={active}
              label="Цель канала"
              value={cfg.core.angle}
              onChange={(angle) => onUpdateGroup("core", { angle })}
            />
          </ProfileSyncRow>
          <ProfileSyncRow active={active} syncKey={`${cfg.core.audience}\u0000${cfg.core.promise}`}>
            <Area
              active={active}
              label="Целевая аудитория"
              value={cfg.core.audience}
              onChange={(audience) => onUpdateGroup("core", { audience })}
            />
            <Area
              active={active}
              label="Ценность для аудитории"
              value={cfg.core.promise}
              onChange={(promise) => onUpdateGroup("core", { promise })}
            />
          </ProfileSyncRow>
        </div>
        <Area
          active={active}
          label="Портрет автора"
          value={cfg.core.author}
          onChange={(author) => onUpdateGroup("core", { author })}
        />
      </ChannelSubsection>

      <div className="profile-channel-divider" />

      <ChannelSubsection title="Голос и формат">
        <div className="profile-grid">
          <ProfileSyncRow active={active} syncKey={`${cfg.voice.tone}\u0000${cfg.voice.phrases}`}>
            <Area
              active={active}
              label="Тон"
              value={cfg.voice.tone}
              onChange={(tone) => onUpdateGroup("voice", { tone })}
            />
            <Area
              active={active}
              label="Обращение к читателю"
              value={cfg.voice.phrases}
              onChange={(phrases) => onUpdateGroup("voice", { phrases })}
            />
          </ProfileSyncRow>
        </div>
        <Area
          active={active}
          label="Базовый формат поста"
          value={cfg.voice.format}
          onChange={(format) => onUpdateGroup("voice", { format })}
        />
      </ChannelSubsection>

      <div className="profile-channel-divider" />

      <ChannelSubsection title="Правила">
        <div className="profile-grid">
          <ProfileSyncRow active={active} syncKey={`${cfg.rules.must}\u0000${cfg.rules.avoid}`}>
            <Area
              active={active}
              label="Обязательно"
              value={cfg.rules.must}
              onChange={(must) => onUpdateGroup("rules", { must })}
            />
            <Area
              active={active}
              label="Избегать"
              value={cfg.rules.avoid}
              onChange={(avoid) => onUpdateGroup("rules", { avoid })}
            />
          </ProfileSyncRow>
        </div>
      </ChannelSubsection>

      <div className="profile-action-buttons profile-action-buttons--ai">
        <button className="btn btn-primary" disabled={!channelProfileDirty} onClick={onSave} type="button">
          Сохранить
        </button>
        {channelProfileDirty ? (
          <button className="btn btn-ghost" onClick={onReset} type="button">
            Отменить
          </button>
        ) : null}
      </div>
    </div>
  );
}
