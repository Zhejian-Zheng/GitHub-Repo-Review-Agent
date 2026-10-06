import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e", use: { baseURL: "http://127.0.0.1:4173", ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) },
  webServer: {
    command: "npm run dev -- --host 127.0.0.1 --port 4173 --strictPort",
    url: "http://127.0.0.1:4173", reuseExistingServer: false,
    env: { VITE_SUPABASE_URL: "http://127.0.0.1:4173/mock-auth", VITE_SUPABASE_ANON_KEY: "test-key", VITE_API_BASE_URL: "http://127.0.0.1:4173/mock-api" }
  }
});
