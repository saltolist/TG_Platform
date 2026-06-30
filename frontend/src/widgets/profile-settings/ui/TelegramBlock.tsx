"use client";

import TelegramApiCredentialsSection from "@/widgets/profile-settings/ui/telegram/TelegramApiCredentialsSection";
import TelegramAuthSection from "@/widgets/profile-settings/ui/telegram/TelegramAuthSection";
import TelegramChannelSection from "@/widgets/profile-settings/ui/telegram/TelegramChannelSection";
import TelegramOmnibotSection from "@/widgets/profile-settings/ui/telegram/TelegramOmnibotSection";
import TelegramStatusHeader from "@/widgets/profile-settings/ui/telegram/TelegramStatusHeader";
import { useTelegramBlock } from "@/widgets/profile-settings/model/useTelegramBlock";

export default function TelegramBlock({ active = true }: { active?: boolean }) {
  const tg = useTelegramBlock();

  return (
    <div className="profile-section">
      <div className="profile-section-title">Telegram</div>

      <TelegramStatusHeader
        status={tg.status}
        isAuthorized={tg.isAuthorized}
        isConnected={tg.isConnected}
        syncing={tg.syncing}
        importing={tg.importing}
        liveSyncing={tg.liveSyncing}
        onReset={tg.reset}
      />

      <div className="telegram-form-grid">
        <TelegramApiCredentialsSection
          active={active}
          cfg={tg.cfg}
          apiChangedFromSaved={tg.apiChangedFromSaved}
          apiIdMissing={tg.apiIdMissing}
          apiHashMissing={tg.apiHashMissing}
          credentialsFlashNonce={tg.credentialsFlashNonce}
          saving={tg.savingCredentials}
          onApiIdChange={(apiId) => tg.update({ apiId })}
          onApiHashChange={(apiHash) => tg.update({ apiHash })}
          onSave={tg.saveApiCredentials}
          onCancel={tg.cancelApiCredentials}
        />

        <TelegramAuthSection
          cfg={tg.cfg}
          codeHidden={tg.codeHidden}
          awaitingPassword={tg.awaitingPassword}
          code={tg.code}
          password={tg.password}
          resendCooldownSec={tg.resendCooldownSec}
          sendCodeDisabled={tg.sendCodeDisabled}
          verifyingCode={tg.verifyingCode}
          verifyingPassword={tg.verifyingPassword}
          onPhoneChange={(phone) => tg.update({ phone })}
          onCodeChange={tg.setCode}
          onPasswordChange={tg.setPassword}
          onStartAuth={tg.startAuth}
          onConfirmCode={tg.confirmCode}
          onConfirmPassword={tg.confirmPassword}
          onCancelCodeEntry={tg.cancelCodeEntry}
          onResendCode={tg.resendCode}
        />
      </div>

      <TelegramChannelSection
        cfg={tg.cfg}
        isAuthorized={tg.isAuthorized}
        isConnected={tg.isConnected}
        connectChannelDisabled={tg.connectChannelDisabled}
        connecting={tg.connectingChannel}
        importing={tg.importing}
        onChannelChange={(channel) => tg.update({ channel })}
        onConnectChannel={tg.connectChannel}
      />

      <div className="telegram-section-divider" aria-hidden />

      <TelegramOmnibotSection
        cfg={tg.cfg}
        isBotConnected={tg.isBotConnected}
        addBotDisabled={tg.addBotDisabled}
        connecting={tg.connectingBot}
        onBotTokenChange={(botApiToken) => tg.update({ botApiToken })}
        onConnectBot={tg.connectBot}
      />
    </div>
  );
}
