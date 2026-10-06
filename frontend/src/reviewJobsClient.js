import { authConfig, backendUrl } from "./authClient";
const abortError = () => new DOMException("Review tracking stopped.", "AbortError");

// Bounds token refresh, fetch and body reads, even if an operation ignores abort.
async function bounded(operation, signal, timeoutMs) {
  const controller = new AbortController();
  let timer, onAbort;
  const stopped = new Promise((_, reject) => {
    onAbort = () => { controller.abort(); reject(abortError()); };
    if (signal?.aborted) return onAbort();
    signal?.addEventListener("abort", onAbort, { once: true });
    timer = setTimeout(() => {
      controller.abort();
      const error = new Error("Review request timed out.");
      error.retryable = true;
      reject(error);
    }, Math.max(0, timeoutMs));
  });
  try {
    if (signal?.aborted) return await stopped;
    return await Promise.race([operation(controller.signal), stopped]);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onAbort);
  }
}
export function submitReviewJob(payload, accessToken, options = {}) {
  return request("/review/jobs", { ...options, method: "POST", accessToken, body: payload });
}
export function cancelReviewJob(jobId, accessToken, options = {}) {
  return request(`/review/jobs/${encodeURIComponent(jobId)}/cancel`, { ...options, method: "POST", accessToken });
}
export function askReportQuestion(payload, accessToken, options = {}) {
  return request("/review/questions", { ...options, method: "POST", accessToken, body: payload });
}
export function fetchReviewJob(jobId, accessToken, options = {}) {
  return request(`/review/jobs/${encodeURIComponent(jobId)}`, { ...options, method: "GET", accessToken });
}
export async function waitForReviewJob(jobId, accessToken, {
  onUpdate, getAccessToken, signal, pollIntervalMs = 1200,
  timeoutMs = 900000, requestTimeoutMs = 15000, maxRetries = 3
} = {}) {
  const deadline = Date.now() + timeoutMs;
  let failures = 0;
  while (Date.now() < deadline) {
    let job;
    try {
      job = await bounded(async (requestSignal) => {
        const token = getAccessToken ? await getAccessToken(requestSignal) : accessToken;
        if (requestSignal.aborted) throw abortError();
        return fetchReviewJob(jobId, token, { signal: requestSignal, timeoutMs: requestTimeoutMs });
      }, signal, Math.min(requestTimeoutMs, deadline - Date.now()));
      failures = 0;
    } catch (error) {
      if (signal?.aborted || error.name === "AbortError") throw error;
      if (Date.now() >= deadline) break;
      if (!(error.retryable || error instanceof TypeError) || ++failures > maxRetries) throw error;
      await delay(Math.min(pollIntervalMs * failures, deadline - Date.now()), signal);
      continue;
    }
    onUpdate?.(job);
    if (job.status === "completed") return job.result;
    if (job.status === "cancelled") throw new Error("Review cancelled.");
    if (job.status === "failed") throw new Error(job.error || "Review job failed.");
    await delay(Math.min(pollIntervalMs, deadline - Date.now()), signal);
  }
  throw new Error("Review job timed out. You can resume tracking this job.");
}
async function request(path, { method, accessToken, body, signal, timeoutMs = 15000 } = {}) {
  return bounded(async (requestSignal) => {
    const headers = { Accept: "application/json" };
    if (body) headers["Content-Type"] = "application/json";
    if (authConfig.apiToken) headers["X-Repo-Review-Token"] = authConfig.apiToken;
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
    const response = await fetch(backendUrl(path), {
      method, headers, signal: requestSignal, body: body ? JSON.stringify(body) : undefined
    });
    const text = await response.text();
    let data;
    try { data = text ? JSON.parse(text) : null; } catch { data = null; }
    if (!response.ok) {
      const error = new Error(data?.detail || `Review backend returned HTTP ${response.status}.`);
      error.retryable = response.status === 429 || response.status >= 500;
      throw error;
    }
    if (!data) throw new Error("Review backend returned an invalid or empty response.");
    return data;
  }, signal, timeoutMs);
}
function delay(ms, signal) {
  return new Promise((resolve, reject) => {
    const onAbort = () => { clearTimeout(timer); reject(abortError()); };
    const timer = setTimeout(() => { signal?.removeEventListener("abort", onAbort); resolve(); }, ms);
    if (signal?.aborted) onAbort();
    else signal?.addEventListener("abort", onAbort, { once: true });
  });
}
