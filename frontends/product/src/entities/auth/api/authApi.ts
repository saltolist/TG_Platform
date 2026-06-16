import { apiRequest } from "@/shared/api/httpClient";
import { apiV1Path } from "@/shared/config/basePath";
import type {
  AuthSession,
  ForgotPasswordResetDto,
  ForgotPasswordSendCodeDto,
  LoginDto,
  RegisterSendCodeDto,
  RegisterVerifyDto,
} from "@/shared/lib/auth/types";

export async function login(dto: LoginDto): Promise<AuthSession> {
  return apiRequest<AuthSession>(apiV1Path("auth/login"), { method: "POST", body: dto });
}

export async function logout(): Promise<void> {
  await apiRequest<void>(apiV1Path("auth/logout"), { method: "POST" });
}

export async function registerSendCode(dto: RegisterSendCodeDto): Promise<void> {
  await apiRequest<void>(apiV1Path("auth/register/send-code"), { method: "POST", body: dto });
}

export async function registerVerify(dto: RegisterVerifyDto): Promise<AuthSession> {
  return apiRequest<AuthSession>(apiV1Path("auth/register/verify"), { method: "POST", body: dto });
}

export async function forgotPasswordSendCode(dto: ForgotPasswordSendCodeDto): Promise<void> {
  await apiRequest<void>(apiV1Path("auth/forgot-password/send-code"), { method: "POST", body: dto });
}

export async function forgotPasswordReset(dto: ForgotPasswordResetDto): Promise<void> {
  await apiRequest<void>(apiV1Path("auth/forgot-password/reset"), { method: "POST", body: dto });
}
