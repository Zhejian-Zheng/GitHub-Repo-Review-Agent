import { useEffect, useState } from "react";
import { clearStoredSession, consumeSessionFromUrl, getCurrentUser, getValidSession, loadStoredSession, saveStoredSession, sessionGeneration, signInWithPassword, signUpWithPassword } from "../authClient";
import { friendlyAuthError } from "../authMessages";

export function useAuthSession(isChinese) {
  const [authSession, setAuthSession] = useState(() => loadStoredSession());
  const [isGuestMode, setIsGuestMode] = useState(false);
  const [authStatus, setAuthStatus] = useState("");
  useEffect(() => {
    let urlSession = null;
    try {
      urlSession = consumeSessionFromUrl();
    } catch (error) {
      setAuthStatus(friendlyAuthError(error.message, isChinese));
      return undefined;
    }
    const session = urlSession || loadStoredSession();
    if (!session?.access_token) return undefined;

    setAuthSession(session);
    let isMounted = true;
    const generation = sessionGeneration();
    getValidSession(session)
      .then((validSession) => {
        if (!validSession?.access_token) {
          throw new Error(isChinese ? "登录已过期，请重新登录。" : "Session expired. Sign in again.");
        }
        return getCurrentUser(validSession.access_token).then((user) => ({ validSession, user }));
      })
      .then((user) => {
        if (!isMounted || generation !== sessionGeneration()) return;
        const nextSession = { ...user.validSession, user: user.user };
        saveStoredSession(nextSession);
        setAuthSession(nextSession);
      })
      .catch((error) => {
        if (!isMounted || generation !== sessionGeneration()) return;
        clearStoredSession();
        setAuthSession(null);
        setAuthStatus(error.message);
      });
    return () => {
      isMounted = false;
    };
  }, []);

  const handleSignIn = async ({ email, password }) => {
    setAuthStatus(isChinese ? "正在登录..." : "Signing in...");
    const session = await signInWithPassword(email, password);
    if (!session) return;
    const generation = sessionGeneration();
    const user = session.user || (await getCurrentUser(session.access_token));
    if (generation !== sessionGeneration()) return;
    const nextSession = { ...session, user };
    saveStoredSession(nextSession);
    setAuthSession(nextSession);
    setIsGuestMode(false);
    setAuthStatus(isChinese ? "已登录，后续评审会保存历史。" : "Signed in. Review history will be saved.");
  };

  const handleSignUp = async ({ email, password }) => {
    setAuthStatus(isChinese ? "正在创建账号..." : "Creating account...");
    const session = await signUpWithPassword(email, password);
    if (!session) return;
    if (session.pending_confirmation || !session.access_token) {
      setAuthStatus(
        isChinese
          ? "账号已创建。请查看邮箱完成验证，然后回到这里登录。"
          : "Account created. Check your email to confirm it, then return here to sign in."
      );
      return;
    }
    if (!session) return;
    const generation = sessionGeneration();
    const user = session.user || (await getCurrentUser(session.access_token));
    if (generation !== sessionGeneration()) return;
    const nextSession = { ...session, user };
    saveStoredSession(nextSession);
    setAuthSession(nextSession);
    setIsGuestMode(false);
    setAuthStatus(isChinese ? "账号已创建，后续评审会保存历史。" : "Account created. Review history will be saved.");
  };

  const handleGuestContinue = () => {
    setIsGuestMode(true);
    setAuthStatus(
      isChinese
        ? "游客模式已启用。可以查看 Demo；如需保存历史或运行受保护后端，请登录账号。"
        : "Guest mode enabled. You can view the demo; sign in to save history or use protected backend reviews."
    );
  };

  const ensureFreshSession = async (session = authSession, options = {}) => {
    if (!session?.access_token) return null;
    const generation = sessionGeneration();
    try {
      const nextSession = await getValidSession(session, options);
      if (options.signal?.aborted || generation !== sessionGeneration()) return null;
      if (!nextSession?.access_token) {
        clearStoredSession();
        setAuthSession(null);
        setAuthStatus(isChinese ? "登录已过期，请重新登录。" : "Session expired. Sign in again.");
        return null;
      }
      if (nextSession.access_token !== session.access_token) {
        const user = nextSession.user || session.user || (await getCurrentUser(nextSession.access_token));
        if (options.signal?.aborted || generation !== sessionGeneration()) return null;
        const refreshedSession = { ...nextSession, user };
        saveStoredSession(refreshedSession);
        setAuthSession(refreshedSession);
        return refreshedSession;
      }
      return nextSession;
    } catch (error) {
      if (options.signal?.aborted || generation !== sessionGeneration()) return null;
      clearStoredSession();
      setAuthSession(null);
      setAuthStatus(friendlyAuthError(error.message, isChinese));
      return null;
    }
  };

  const endSession = () => {
    clearStoredSession();
    setAuthSession(null);
    setIsGuestMode(false);
    setAuthStatus(isChinese ? "已退出登录。" : "Signed out.");
  };
  return { authSession, setAuthSession, isGuestMode, setIsGuestMode, authStatus,
    handleSignIn, handleSignUp, handleGuestContinue, ensureFreshSession, endSession };
}
