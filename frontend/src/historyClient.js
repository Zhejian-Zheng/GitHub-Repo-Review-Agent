import { authConfig, isAuthConfigured } from "./authClient";

export async function fetchRepositories(accessToken) {
  return restRequest(
    "repositories?select=id,repo_url,repo_name,default_branch,created_at,updated_at&order=updated_at.desc",
    accessToken
  );
}

export async function fetchProjectDetail(repositoryId, accessToken) {
  const runs = await restRequest(
    [
      "review_runs",
      `?repository_id=eq.${encodeURIComponent(repositoryId)}`,
      "&select=id,status,commit_sha,branch,health_score,new_findings_count,existing_findings_count,resolved_findings_count,created_at,metrics_json,diff_json",
      "&order=created_at.desc",
      "&limit=12"
    ].join(""),
    accessToken
  );
  const latestRun = runs[0] || null;
  if (!latestRun) {
    return { runs, latestRun: null, findings: [], aiReview: null };
  }

  const [findings, aiReviews] = await Promise.all([
    restRequest(
      [
        "findings",
        `?review_run_id=eq.${encodeURIComponent(latestRun.id)}`,
        "&select=fingerprint,title,severity,category,evidence_json,evidence_paths_json,recommendation,status,created_at"
      ].join(""),
      accessToken
    ),
    restRequest(
      [
        "ai_reviews",
        `?review_run_id=eq.${encodeURIComponent(latestRun.id)}`,
        "&select=provider,model,status,summary,error,sections_json,created_at",
        "&limit=1"
      ].join(""),
      accessToken
    )
  ]);

  return {
    runs,
    latestRun,
    findings: sortFindings(findings),
    aiReview: aiReviews[0] || null
  };
}

async function restRequest(path, accessToken) {
  if (!isAuthConfigured()) {
    throw new Error("Supabase auth is not configured.");
  }
  if (!accessToken) {
    throw new Error("Sign in before viewing project history.");
  }

  const response = await fetch(`${authConfig.supabaseUrl.replace(/\/$/, "")}/rest/v1/${path}`, {
    headers: {
      apikey: authConfig.anonKey,
      Authorization: `Bearer ${accessToken}`,
      Accept: "application/json"
    }
  });
  const text = await response.text();
  const data = text ? JSON.parse(text) : [];
  if (!response.ok) {
    throw new Error(data?.message || data?.hint || data?.details || "History request failed.");
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
