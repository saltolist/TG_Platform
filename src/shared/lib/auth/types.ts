export type AuthSession = {
  token: string;
  accountId: string;
  email: string;
  createdAt: string;
};

export type LoginDto = {
  email: string;
  password: string;
};

export type RegisterSendCodeDto = {
  email: string;
  password: string;
};

export type RegisterVerifyDto = {
  email: string;
  code: string;
};

export type ForgotPasswordSendCodeDto = {
  email: string;
};

export type ForgotPasswordResetDto = {
  email: string;
  code: string;
  password: string;
};
