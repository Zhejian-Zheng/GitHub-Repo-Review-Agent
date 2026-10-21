import { beforeEach, afterEach, expect, test, vi } from "vitest";
import { authConfig, clearStoredSession, getValidSession, refreshSession, saveStoredSession, loadStoredSession, sessionGeneration } from "./authClient";

beforeEach(() => {
  const entries = new Map();
  vi.stubGlobal("window", { localStorage: {
    getItem: key => entries.get(key) ?? null,
    setItem: (key, value) => entries.set(key, value),
    removeItem: key => entries.delete(key)
  }});
  authConfig.supabaseUrl = "https://auth.example";
  authConfig.anonKey = "test";
});
afterEach(() => vi.unstubAllGlobals());

test("a delayed refresh cannot restore a session after logout", async () => {
  let release;
  vi.stubGlobal("fetch", vi.fn(() => new Promise(resolve => { release = resolve; })));
  saveStoredSession({ access_token: "old", refresh_token: "refresh" });
  const pending = refreshSession("refresh");
  clearStoredSession();
  release({ ok: true, text: async () => JSON.stringify({ access_token: "late", refresh_token: "new" }) });
  expect(await pending).toBeNull();
  expect(loadStoredSession()).toBeNull();
});

test("a failed logout still clears local credentials", async () => {
  const { signOut } = await import("./authClient");
  saveStoredSession({ access_token: "old" });
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Offline")));
  await expect(signOut("old")).rejects.toThrow("Offline");
  expect(loadStoredSession()).toBeNull();
});

test("an expired session without a refresh token is reported without a hidden logout", async () => {
  const session = { access_token: "old", expires_at: 1 };
  saveStoredSession(session);
  const generation = sessionGeneration();
  expect(await getValidSession(session)).toBeNull();
  expect(sessionGeneration()).toBe(generation);
  expect(loadStoredSession()).toEqual(session);
});
