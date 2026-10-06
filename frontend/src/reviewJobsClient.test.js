import { afterEach, expect, it, vi } from "vitest";
import { waitForReviewJob, submitReviewJob } from "./reviewJobsClient";
vi.mock("./authClient", () => ({ authConfig: {}, backendUrl: (path) => path }));
const reply = (data, status = 200) => new Response(JSON.stringify(data), { status });
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });
it("retries transient HTTP and network errors and refreshes tokens each poll", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(reply({}, 503)).mockRejectedValueOnce(new TypeError("offline"))
    .mockResolvedValueOnce(reply({ status: "completed", result: { markdown: "done" } }));
  vi.stubGlobal("fetch", fetch);
  const getAccessToken = vi.fn().mockResolvedValueOnce("old").mockResolvedValue("fresh");
  expect(await waitForReviewJob("a", null, { getAccessToken, pollIntervalMs: 1 })).toEqual({ markdown: "done" });
  expect(fetch.mock.calls[2][1].headers.Authorization).toBe("Bearer fresh");
});
it("does not retry authorization errors or failed jobs", async () => {
  const fetch = vi.fn().mockResolvedValue(reply({ detail: "Unauthorized" }, 401));
  vi.stubGlobal("fetch", fetch);
  await expect(waitForReviewJob("a")).rejects.toThrow("Unauthorized");
  expect(fetch).toHaveBeenCalledTimes(1);
  fetch.mockResolvedValue(reply({ status: "failed", error: "Clone failed" }));
  await expect(waitForReviewJob("a")).rejects.toThrow("Clone failed");
});
it("caps retries", async () => {
  const fetch = vi.fn().mockImplementation(() => Promise.resolve(reply({}, 429)));
  vi.stubGlobal("fetch", fetch);
  await expect(waitForReviewJob("a", null, { maxRetries: 2, pollIntervalMs: 1 })).rejects.toThrow("429");
  expect(fetch).toHaveBeenCalledTimes(3);
});
it("cancels an in-flight fetch and a polling delay", async () => {
  let requestSignal;
  vi.stubGlobal("fetch", vi.fn((_url, options) => { requestSignal = options.signal; return new Promise(() => {}); }));
  const controller = new AbortController();
  const promise = waitForReviewJob("a", null, { signal: controller.signal });
  const assertion = expect(promise).rejects.toHaveProperty("name", "AbortError");
  controller.abort();
  await assertion;
  expect(requestSignal.aborted).toBe(true);
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply({ status: "running" })));
  const second = new AbortController();
  await expect(waitForReviewJob("a", null, { signal: second.signal, onUpdate: () => second.abort() })).rejects.toHaveProperty("name", "AbortError");
});
it("bounds hanging fetch, response body and token refresh by the total deadline", async () => {
  for (const kind of ["fetch", "body", "token"]) {
    vi.stubGlobal("fetch", vi.fn(() => kind === "fetch" ? new Promise(() => {}) : Promise.resolve({ ok: true, text: () => new Promise(() => {}) })));
    await expect(waitForReviewJob("a", null, {
      timeoutMs: 20, requestTimeoutMs: 1000,
      ...(kind === "token" ? { getAccessToken: () => new Promise(() => {}) } : {})
    })).rejects.toThrow("Review job timed out");
  }
});
it("bounds submission without automatically duplicating POST requests", async () => {
  const fetch = vi.fn(() => new Promise(() => {}));
  vi.stubGlobal("fetch", fetch);
  await expect(submitReviewJob({}, null, { timeoutMs: 10 })).rejects.toThrow("request timed out");
  expect(fetch).toHaveBeenCalledTimes(1);
});
it("treats server cancellation as terminal without another poll", async () => {
  const fetch = vi.fn().mockImplementation(() => Promise.resolve(reply({ job_id: "a", status: "cancelled" })));
  vi.stubGlobal("fetch", fetch);
  await expect(waitForReviewJob("a", null, { timeoutMs: 30, pollIntervalMs: 1 })).rejects.toThrow("cancelled");
  expect(fetch).toHaveBeenCalledTimes(1);
});
