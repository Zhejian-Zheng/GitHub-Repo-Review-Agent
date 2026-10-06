import { backendUrl } from "./authClient";

export async function fetchRepositories(accessToken) {
  const data = await backendRequest("/history/repositories", accessToken);
  return data.repositories || [];
}

export async function fetchProjectDetail(repositoryId, accessToken) {
  const detail = await backendRequest(
    `/history/repositories/${encodeURIComponent(repositoryId)}`,
    accessToken
  );
  return {
    ...detail,
    findings: sortFindings(detail.findings || [])
  };
}

export function saveFindingFeedback(repositoryId, fingerprint, payload, accessToken) {
  return backendRequest(`/history/repositories/${encodeURIComponent(repositoryId)}/findings/${encodeURIComponent(fingerprint)}/feedback`, accessToken, {
    method: "POST", body: JSON.stringify(payload), headers: { "Content-Type": "application/json" }
  });
}

async function backendRequest(path, accessToken, options = {}) {
  if (!accessToken) {
    throw new Error("Sign in before viewing project history.");
  }

  const response = await fetch(backendUrl(path), {
    ...options,
    headers: {
      Authorization: `Bearer ${accessToken}`,
      Accept: "application/json",
      ...options.headers
    }
  });
  const text = await response.text();
  const data = text ? JSON.parse(text) : [];
  if (!response.ok) {
    throw new Error(data?.detail || data?.message || data?.hint || data?.details || "History request failed.");
  }
  return data;
}

function sortFindings(findings) {
  const severityRank = {
    high: 0,
    medium: 1,
    low: 2,
    info: 3
  };
  return [...findings].sort((left, right) => {
    const leftRank = severityRank[left.severity] ?? 4;
    const rightRank = severityRank[right.severity] ?? 4;
    if (leftRank !== rightRank) return leftRank - rightRank;
    return String(left.title).localeCompare(String(right.title));
  });
}
