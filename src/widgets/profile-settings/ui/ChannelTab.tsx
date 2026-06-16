"use client";

import ChannelProfileSection from "@/widgets/profile-settings/ui/channel/ChannelProfileSection";
import ChannelRubricsSection from "@/widgets/profile-settings/ui/channel/ChannelRubricsSection";
import { useChannelTab } from "@/widgets/profile-settings/model/useChannelTab";
import { useChannelConnected } from "@/entities/channel";
import { ConnectChannelEmptyState } from "@/features/connect-channel";

export default function ChannelTab({ active }: { active: boolean }) {
  const ch = useChannelTab();
  const { isConnected: isChannelConnected, isLoading: isChannelLoading } = useChannelConnected();

  return (
    <div className={`profile-panel profile-panel--channel${active ? " active" : ""}`}>
      {isChannelLoading ? (
        <p className="screen-placeholder">Загрузка…</p>
      ) : !isChannelConnected ? (
        <ConnectChannelEmptyState feature="базе знаний канала" icon="📚" />
      ) : (
        <>
          <div className="profile-channel-actions">
            <div>
              <div className="profile-section-title">Канал как база знаний ИИ</div>
              <div className="profile-val profile-muted">
                Всё, что заполнено здесь, становится глобальным контекстом канала и наследуется
                локальными чатами постов.
              </div>
            </div>
          </div>

          <ChannelProfileSection
            active={active}
            cfg={ch.cfg}
            channelProfileDirty={ch.channelProfileDirty}
            onUpdateGroup={ch.updateGroup}
            onSave={ch.saveChannelProfile}
            onReset={ch.resetChannelProfile}
          />

          <ChannelRubricsSection
            active={active}
            cfg={ch.cfg}
            rubricsDirty={ch.rubricsDirty}
            onAddRubric={ch.addRubric}
            onUpdateRubric={ch.updateRubric}
            onRemoveRubric={ch.removeRubric}
            onSave={ch.saveRubrics}
            onReset={ch.resetRubrics}
          />

          <div className="profile-section profile-section-muted">
            <div className="profile-section-title">Технические настройки</div>
            <div className="profile-val profile-muted">
              ИИ-движок, системный промпт, метрики ИИ и Telegram подключение редактируются на
              вкладке «Настройки», чтобы не смешивать базу знаний канала с техническими
              интеграциями.
            </div>
          </div>
        </>
      )}
    </div>
  );
}
