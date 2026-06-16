import { GuestGuard } from "@/features/auth-guard";
import { LoginScreen } from "@/screens/login/LoginScreen";

export default function LoginPage() {
  return (
    <GuestGuard>
      <LoginScreen />
    </GuestGuard>
  );
}
