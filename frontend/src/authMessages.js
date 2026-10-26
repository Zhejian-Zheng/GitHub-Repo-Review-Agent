export function friendlyAuthError(message, isChinese) {
  if (/otp.*expired/i.test(message || "") || /email link is invalid/i.test(message || "")) {
    return isChinese
      ? "邮箱确认链接已失效。请回到登录页重新注册，或在 Supabase 中重新发送确认邮件。"
      : "The email confirmation link expired. Return to sign-up or resend the confirmation email from Supabase.";
  }
  if (/valid bearer token/i.test(message || "") || /bearer token/i.test(message || "")) {
    return isChinese
      ? "登录凭证无效或已过期。请重新登录；如果刚注册，请先完成邮箱验证。"
      : "Your sign-in session is missing or expired. Sign in again; if you just registered, confirm your email first.";
  }
  if (/email not confirmed/i.test(message || "")) {
    return isChinese ? "请先完成邮箱验证，然后再登录。" : "Confirm your email before signing in.";
  }
  if (/invalid login credentials/i.test(message || "")) {
    return isChinese ? "邮箱或密码不正确。" : "Email or password is incorrect.";
  }
  return message;
}

