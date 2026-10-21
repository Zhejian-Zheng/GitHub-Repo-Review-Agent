import React, { useState } from "react";
import { LogIn, LogOut, RotateCcw, UserPlus, UserRound } from "lucide-react";
export function AuthGate({
  language,
  status,
  onSignIn,
  onSignUp,
  onGuestContinue,
  onSetLanguage,
  formatError = (error) => error
}) {
  const [mode, setMode] = useState("sign-in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");
  const isChinese = language === "zh-CN";

  const submitAuth = async (event) => {
    event.preventDefault();
    setError("");
    if (mode === "sign-up" && password !== confirmPassword) {
      setError(isChinese ? "两次输入的密码不一致。" : "Passwords do not match.");
      return;
    }
    setIsSubmitting(true);
    try {
      if (mode === "sign-up") {
        await onSignUp({ email, password });
        setMode("sign-in");
      } else {
        await onSignIn({ email, password });
      }
      setPassword("");
      setConfirmPassword("");
    } catch (authError) {
      setError(formatError(authError.message));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <main className="auth-page">
      <header className="auth-page-topbar">
        <button className="brand-menu auth-brand" type="button" aria-label="RepoGPT">
          <span>RepoGPT</span>
        </button>
        <div className="language-toggle" role="group" aria-label="Report language">
          <button
            className={isChinese ? "active" : ""}
            type="button"
            onClick={() => onSetLanguage("zh-CN")}
            aria-pressed={isChinese}
          >
            中文
          </button>
          <button
            className={!isChinese ? "active" : ""}
            type="button"
            onClick={() => onSetLanguage("en")}
            aria-pressed={!isChinese}
          >
            EN
          </button>
        </div>
      </header>

      <section className="auth-hero" aria-labelledby="auth-title">
        <div className="auth-intro">
          <p className="auth-eyebrow">{isChinese ? "仓库评审工作台" : "Repository review workspace"}</p>
          <h1 id="auth-title">
            {isChinese ? "登录后追踪每一次仓库健康变化" : "Sign in to track every repository review"}
          </h1>
          <p>
            {isChinese
              ? "保存历史扫描、查看趋势、比较新增和已解决问题。游客可以先进入体验内置 Demo。"
              : "Save review history, inspect trends, and compare new or resolved findings. Guests can continue to try the built-in demo first."}
          </p>
          <div className="auth-feature-row">
            <span>{isChinese ? "Supabase 登录" : "Supabase auth"}</span>
            <span>{isChinese ? "历史记录" : "Review history"}</span>
            <span>{isChinese ? "游客体验" : "Guest access"}</span>
          </div>
        </div>

        <form className="auth-card" onSubmit={submitAuth}>
          <div className="auth-card-head">
            <UserRound size={24} aria-hidden="true" />
            <div>
              <h2>{mode === "sign-up" ? (isChinese ? "创建账号" : "Create account") : isChinese ? "欢迎回来" : "Welcome back"}</h2>
              <p>{isChinese ? "使用邮箱和密码继续。" : "Continue with email and password."}</p>
            </div>
          </div>

          <div className="auth-tabs auth-tabs-large" role="tablist" aria-label="Authentication mode">
            <button
              className={mode === "sign-in" ? "active" : ""}
              type="button"
              onClick={() => setMode("sign-in")}
            >
              {isChinese ? "登录" : "Sign in"}
            </button>
            <button
              className={mode === "sign-up" ? "active" : ""}
              type="button"
              onClick={() => setMode("sign-up")}
            >
              {isChinese ? "注册" : "Sign up"}
            </button>
          </div>

          <label className="auth-field">
            <span>{isChinese ? "邮箱" : "Email"}</span>
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@example.com"
              autoComplete="email"
              required
            />
          </label>

          <label className="auth-field">
            <span>{isChinese ? "密码" : "Password"}</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder={isChinese ? "至少 6 位" : "At least 6 characters"}
              autoComplete={mode === "sign-up" ? "new-password" : "current-password"}
              minLength={6}
              required
            />
          </label>

          {mode === "sign-up" ? (
            <label className="auth-field">
              <span>{isChinese ? "确认密码" : "Confirm password"}</span>
              <input
                type="password"
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                placeholder={isChinese ? "再次输入密码" : "Enter password again"}
                autoComplete="new-password"
                minLength={6}
                required
              />
            </label>
          ) : null}

          <button className="auth-primary-button" type="submit" disabled={isSubmitting}>
            {isSubmitting ? (
              <RotateCcw size={18} className="animate-spin" aria-hidden="true" />
            ) : mode === "sign-up" ? (
              <UserPlus size={18} aria-hidden="true" />
            ) : (
              <LogIn size={18} aria-hidden="true" />
            )}
            {mode === "sign-up" ? (isChinese ? "创建账号" : "Create account") : isChinese ? "登录" : "Sign in"}
          </button>

          <button className="auth-guest-button" type="button" onClick={onGuestContinue}>
            <UserRound size={18} aria-hidden="true" />
            {isChinese ? "游客继续" : "Continue as guest"}
          </button>

          {error || status ? <p className={error ? "auth-error" : "auth-status"}>{error || status}</p> : null}
        </form>
      </section>
    </main>
  );
}

export function GuestPanel({ language, onSignIn }) {
  const isChinese = language === "zh-CN";
  return (
    <div className="auth-compact guest">
      <UserRound size={16} aria-hidden="true" />
      <span>{isChinese ? "游客模式" : "Guest"}</span>
      <button className="auth-login-button" type="button" onClick={onSignIn}>
        {isChinese ? "登录" : "Sign in"}
      </button>
    </div>
  );
}

export function AuthPanel({
  configured,
  session,
  status,
  language,
  onSignIn,
  onSignUp,
  onSignOut,
  formatError = (error) => error
}) {
  const [mode, setMode] = useState("sign-in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");
  const isChinese = language === "zh-CN";
  const userEmail = session?.user?.email;

  if (!configured) {
    return (
      <div className="auth-compact unavailable" title="Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY">
        <UserRound size={16} aria-hidden="true" />
        <span>{isChinese ? "未配置登录" : "Auth off"}</span>
      </div>
    );
  }

  if (session?.access_token) {
    return (
      <div className="auth-compact signed-in">
        <UserRound size={16} aria-hidden="true" />
        <span title={userEmail || "Signed in"}>{userEmail || (isChinese ? "已登录" : "Signed in")}</span>
        <button className="auth-icon-button" type="button" onClick={onSignOut} aria-label="Sign out">
          <LogOut size={16} aria-hidden="true" />
        </button>
      </div>
    );
  }

  const submitAuth = async (event) => {
    event.preventDefault();
    setError("");
    setIsSubmitting(true);
    try {
      if (mode === "sign-up") {
        await onSignUp({ email, password });
        setMode("sign-in");
      } else {
        await onSignIn({ email, password });
      }
      setPassword("");
    } catch (authError) {
      setError(formatError(authError.message));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <form className="auth-panel" onSubmit={submitAuth}>
      <div className="auth-tabs" role="tablist" aria-label="Authentication mode">
        <button
          className={mode === "sign-in" ? "active" : ""}
          type="button"
          onClick={() => setMode("sign-in")}
        >
          {isChinese ? "登录" : "Sign in"}
        </button>
        <button
          className={mode === "sign-up" ? "active" : ""}
          type="button"
          onClick={() => setMode("sign-up")}
        >
          {isChinese ? "注册" : "Sign up"}
        </button>
      </div>
      <input
        type="email"
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        placeholder="email"
        aria-label="Email"
        required
      />
      <input
        type="password"
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        placeholder="password"
        aria-label="Password"
        minLength={6}
        required
      />
      <button className="auth-submit" type="submit" disabled={isSubmitting}>
        {isSubmitting ? (
          <RotateCcw size={15} className="animate-spin" aria-hidden="true" />
        ) : (
          <LogIn size={15} aria-hidden="true" />
        )}
        {mode === "sign-up" ? (isChinese ? "注册" : "Join") : isChinese ? "登录" : "Login"}
      </button>
      {error || status ? <p className={error ? "auth-error" : "auth-status"}>{error || status}</p> : null}
    </form>
  );
}

