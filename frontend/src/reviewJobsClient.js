import { authConfig } from "./authClient";

const DEFAULT_POLL_INTERVAL_MS = 1200;
const DEFAULT_TIMEOUT_MS = 15 * 60 * 1000;

export async function submitReviewJob(payload, accessToken) {
  return reviewJobRequest("/review/jobs", {
    method: "POST",
    accessToken,
    body: payload
  });
}

export async function fetchReviewJob(jobId, accessToken) {
  return reviewJobRequest(`/review/jobs/${encodeURIComponent(jobId)}`, {
    method: "GET",
    accessToken
  });
}

export async function waitForReviewJob(
  jobId,
  accessToken,
  {
    onUpdate,
    pollIntervalMs = DEFAULT_POLL_INTERVAL_MS,
    timeoutMs = DEFAULT_TIMEOUT_MS
  } = {}
) {
  const startedAt = Date.now();
  while (Date.now() - startedAt <= timeoutMs) {
    const job = await fetchReviewJob(jobId, accessToken);
    onUpdate?.(job);
    if (job.status === "completed") {
      return job.result;
    }
    if (job.status === "failed") {
      throw new Error(job.error || "Review job failed.");
    }
    await delay(pollIntervalMs);
  }
  throw new Error("Review job timed out.");
}

async function reviewJobRequest(path, { method, accessToken, body } = {}) {
  const headers = {
    Accept: "application/json"
  };
  if (body) {
    headers["Content-Type"] = "application/json";
  }
  if (authConfig.apiToken) {
    headers["X-Repo-Review-Token"] = authConfig.apiToken;
  }
  if (accessToken) {
    headers.Authorization = `Bearer ${accessToken}`;
  }

  const response = await fetch(path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined
  });
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) {
    throw new Error(data?.detail || `Review backend returned HTTP ${response.status}.`);
  }
  if (!data) {
    throw new Error("Review backend returned an empty response.");
  }
  return data;
}

function delay(ms) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}
