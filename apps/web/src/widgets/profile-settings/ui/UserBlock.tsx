"use client";

import { useRouter } from "next/navigation";
import UserEmailCodeStep from "@/widgets/profile-settings/ui/user/UserEmailCodeStep";
import UserPasswordStep from "@/widgets/profile-settings/ui/user/UserPasswordStep";
import UserSendCodePrompt from "@/widgets/profile-settings/ui/user/UserSendCodePrompt";
import { UserSummary } from "@/entities/user";
import { useAuth } from "@/app/providers/AuthProvider";
import { routes } from "@/shared/lib/routes";
import { useUserBlock } from "@/widgets/profile-settings/model/useUserBlock";

export default function UserBlock() {
  const user = useUserBlock();
  const { session, logout } = useAuth();
  const router = useRouter();

  const handleLogout = async () => {
    await logout();
    router.replace(routes.home());
  };

  return (
    <div className="profile-section profile-user-section">
      <div className="profile-section-title">Пользователь</div>

      <UserSummary
        nick={user.defaultUser.nick}
        email={session?.email ?? user.defaultUser.email}
        flow={user.flow}
        onStartChangePassword={user.startChangePassword}
        onLogout={handleLogout}
      />

      {user.flow === "confirm-send" ? (
        <UserSendCodePrompt
          email={user.defaultUser.email}
          onSend={user.sendEmailCode}
          onCancel={user.resetFlow}
        />
      ) : null}

      {user.flow === "code" ? (
        <UserEmailCodeStep
          emailCode={user.emailCode}
          resendCooldownSec={user.resendCooldownSec}
          onEmailCodeChange={user.setEmailCode}
          onConfirm={user.confirmEmailCode}
          onDismiss={user.resetFlow}
          onResend={user.resendEmailCode}
        />
      ) : null}

      {user.flow === "password" ? (
        <UserPasswordStep
          password={user.password}
          passwordConfirm={user.passwordConfirm}
          passwordVisible={user.passwordVisible}
          passwordConfirmVisible={user.passwordConfirmVisible}
          passwordStrength={user.passwordStrength}
          passwordsMismatch={user.passwordsMismatch}
          canConfirm={user.canConfirmPassword}
          onPasswordChange={user.setPassword}
          onPasswordConfirmChange={user.setPasswordConfirm}
          onTogglePasswordVisible={user.togglePasswordVisible}
          onTogglePasswordConfirmVisible={user.togglePasswordConfirmVisible}
          onConfirm={user.confirmNewPassword}
        />
      ) : null}
    </div>
  );
}
