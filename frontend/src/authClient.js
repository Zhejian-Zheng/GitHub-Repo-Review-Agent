const STORAGE_KEY = "repo-review-auth-session";

export const authConfig = {
  supabaseUrl: import.meta.env.VITE_SUPABASE_URL || "",
  anonKey: import.meta.env.VITE_SUPABASE_ANON_KEY || "",
  apiToken: import.meta.env.VITE_REPO_REVIEW_API_TOKEN || ""
};

export function isAuthConfigured() {
  return Boolean(authConfig.supabaseUrl && authConfig.anonKey);
}

export function loadStoredSession() {
  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (!raw) return null;
  try {
    const session = JSON.parse(raw);
    return session?.access_token ? session : null;
  } catch {
    return null;
  }
}

export function saveStoredSession(session) {
  if (!session?.access_token) return;
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
}

export function clearStoredSession() {
  window.localStorage.removeItem(STORAGE_KEY);
}

export function consumeSessionFromUrl() {
  const params = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  const accessToken = params.get("access_token");
  const refreshToken = params.get("refresh_token");
  if (!accessToken) return null;

  const session = {
    access_token: accessToken,
    refresh_token: refreshToken,
    token_type: params.get("token_type") || "bearer",
    expires_in: Number(params.get("expires_in") || 0),
    user: null
  };
  window.history.replaceState(null, document.title, window.location.pathname + window.location.search);
  saveStoredSession(session);
  return session;
}

export async function signInWithPassword(email, password) {
  const data = await authRequest("/token?grant_type=password", {
    method: "POST",
    body: { email, password }
  });
  const session = normalizeSession(data);
  saveStoredSession(session);
  return session;
}

export async function signUpWithPassword(email, password) {
  const data = await authRequest("/signup", {
    method: "POST",
    body: { email, password }
  });
  const session = normalizeSession(data);
  if (session.access_token) {
    saveStoredSession(session);
  }
  return session;
}

export async function getCurrentUser(accessToken) {
  const data = await authRequest("/user", {
    method: "GET",
    accessToken
  });
  return data;
}

export async function signOut(accessToken) {
  if (accessToken) {
    await authRequest("/logout", {
      method: "POST",
      accessToken
    });
  }
  clearStoredSession();
}

function normalizeSession(data) {
  if (data?.session) {
    return {
      ...data.session,
      user: data.session.user || data.user || null
    };
  }
  return {
    access_token: data?.access_token || null,
    refresh_token: data?.refresh_token || null,
    token_type: data?.token_type || "bearer",
    expires_in: data?.expires_in || 0,
    user: data?.user || null,
    pending_confirmation: Boolean(data?.user && !data?.access_token)
  };
}

async function authRequest(path, { method, body, accessToken } = {}) {
  if (!isAuthConfigured()) {
    throw new Error("Supabase auth is not configured.");
  }

  const headers = {
    apikey: authConfig.anonKey,
    "Content-Type": "application/json"
  };
  if (accessToken) {
    headers.Authorization = `Bearer ${accessToken}`;
  }

  const response = await fetch(`${authConfig.supabaseUrl.replace(/\/$/, "")}/auth/v1${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined
  });
  const text = await response.text();
  const data = text ? JSON.parse(text) : {};
  if (!response.ok) {
    throw new Error(data?.msg || data?.message || data?.error_description || data?.error || "Auth failed.");
  }
  return data;
}
