import { Suspense } from "react";
import { GuestGuard } from "@/features/auth-guard";
import { ForgotPasswordScreen } from "@/screens/login/ForgotPasswordScreen";

export default function ForgotPasswordPage() {
  return (
    <GuestGuard>
      <Suspense fallback={null}>
        <ForgotPasswordScreen />
      </Suspense>
    </GuestGuard>
  );
}
