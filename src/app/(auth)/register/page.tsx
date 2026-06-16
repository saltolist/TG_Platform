import { GuestGuard } from "@/features/auth-guard";
import { RegisterScreen } from "@/screens/register/RegisterScreen";

export default function RegisterPage() {
  return (
    <GuestGuard>
      <RegisterScreen />
    </GuestGuard>
  );
}
