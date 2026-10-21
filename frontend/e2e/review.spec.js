import { test, expect } from "@playwright/test";
const user = { id: "user-1", email: "review@example.com" };
async function setup(page) {
  await page.route("**/mock-auth/auth/v1/**", (route) => route.fulfill({ json: route.request().url().endsWith("/user") ? user : { access_token: "token", refresh_token: "refresh", expires_in: 3600, user } }));
  await page.route("**/mock-api/history/repositories", (route) => route.fulfill({ json: { repositories: [{ id: "repo-1", repo_name: "example/project", repo_url: "https://github.com/example/project" }] } }));
  await page.route("**/mock-api/history/repositories/repo-1", (route) => route.fulfill({ json: { latestRun: { health_score: 82 }, findings: [], runs: [] } }));
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: "EN", exact: true }).click();
  await page.getByLabel("Email", { exact: true }).fill(user.email);
  await page.getByLabel("Password", { exact: true }).fill("test-password");
  await page.locator("button.auth-primary-button").click();
  await expect(page.getByRole("button", { name: "Review repository" })).toBeVisible();
}
test("login, real phase display, submit review and open history", async ({ page }) => {
  await setup(page);
  let complete = false;
  await page.route("**/mock-api/review/jobs", (route) => route.fulfill({ json: { job_id: "job-1", status: "queued", phase: "queued" } }));
  await page.route("**/mock-api/review/jobs/job-1", (route) => route.fulfill({ json: complete ? { job_id: "job-1", status: "completed", phase: "completed", result: { markdown: "# Browser review complete" } } : { job_id: "job-1", status: "running", phase: "cloning" } }));
  await page.getByRole("button", { name: "Review repository" }).click();
  await expect(page.locator(".home-status")).toContainText("Prepare repository");
  await page.waitForTimeout(1800);
  await expect(page.locator(".home-status")).toContainText("Prepare repository");
  complete = true;
  await expect(page.locator(".home-status")).toHaveText("Review complete.");
  await page.getByRole("button", { name: "example/project https://github.com/example/project" }).click();
  await expect(page.locator(".project-detail-panel")).toContainText("82");
});
test("failed review can be retried", async ({ page }) => {
  await setup(page);
  let attempts = 0;
  await page.route("**/mock-api/review/jobs", (route) => { attempts++; return route.fulfill({ json: { job_id: "job-2" } }); });
  await page.route("**/mock-api/review/jobs/job-2", (route) => route.fulfill({ json: attempts === 1 ? { job_id: "job-2", status: "failed", phase: "failed", error: "Clone failed" } : { job_id: "job-2", status: "completed", result: { markdown: "# Success" } } }));
  await page.getByRole("button", { name: "Review repository" }).click();
  await expect(page.locator(".home-status")).toContainText("Clone failed");
  await page.getByRole("button", { name: "Review repository" }).click();
  await expect(page.locator(".home-status")).toHaveText("Review complete.");
  expect(attempts).toBe(2);
});
test("stopped tracking resumes after page refresh without another submission", async ({ page }) => {
  await setup(page);
  let submissions = 0;
  await page.route("**/mock-api/review/jobs", (route) => { submissions++; return route.fulfill({ json: { job_id: "job-3" } }); });
  await page.route("**/mock-api/review/jobs/job-3", (route) => route.fulfill({ json: { job_id: "job-3", status: "running", phase: "analyzing" } }));
  await page.getByRole("button", { name: "Review repository" }).click();
  await expect(page.locator(".home-status")).toContainText("Run rule checks");
  await page.getByRole("button", { name: "Stop tracking" }).click();
  await expect(page.getByRole("button", { name: "Resume tracking" })).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "EN", exact: true }).click();
  await page.getByRole("button", { name: "Resume tracking" }).click();
  await expect(page.locator(".home-status")).toContainText("Run rule checks");
  expect(submissions).toBe(1);
});
test("cancel terminates backend job and removes resume state", async ({ page }) => {
  await setup(page);
  await page.route("**/mock-api/review/jobs", route => route.fulfill({ json: { job_id: "cancel-me" } }));
  await page.route("**/mock-api/review/jobs/cancel-me", route => route.fulfill({ json: { job_id: "cancel-me", status: "running", phase: "analyzing" } }));
  await page.route("**/mock-api/review/jobs/cancel-me/cancel", route => route.fulfill({ json: { job_id: "cancel-me", status: "cancelled" } }));
  await page.getByRole("button", { name: "Review repository" }).click();
  await page.getByRole("button", { name: "Cancel review", exact: true }).click();
  await expect(page.locator(".home-status")).toContainText("cancelled");
  await expect(page.getByRole("button", { name: "Resume tracking" })).toHaveCount(0);
});
test("finding feedback persists reason and expiry and refreshes effective score", async ({ page }) => {
  await setup(page);
  let feedback;
  await page.route("**/mock-api/history/repositories/repo-1", route => route.fulfill({ json: {
    latestRun: { health_score: 60 }, effective_health_score: feedback ? 82 : 60,
    findings: [{ fingerprint: "fp-1", title: "Review dependency", recommendation: "Upgrade dependency", severity: "high", feedback }], runs: []
  } }));
  await page.route("**/mock-api/history/repositories/repo-1/findings/fp-1/feedback", route => {
    feedback = route.request().postDataJSON();
    return route.fulfill({ json: feedback });
  });
  await page.getByRole("button", { name: "example/project https://github.com/example/project" }).click();
  await page.getByLabel("Finding decision").selectOption("false_positive");
  await page.getByLabel("Feedback reason").fill("Generated fixture only");
  await page.getByLabel("Feedback expiry").fill("2027-01-01");
  await page.getByRole("button", { name: "Save decision" }).click();
  await expect(page.locator(".project-detail-panel")).toContainText("82");
  expect(feedback.reason).toBe("Generated fixture only");
  expect(feedback.expires_at).toBe("2027-01-01T23:59:59.000Z");
});
test("report follow-up renders evidence and submitted model selection", async ({ page }) => {
  await setup(page);
  let payload;
  await page.route("**/mock-api/review/questions", route => {
    payload = route.request().postDataJSON();
    return route.fulfill({ json: { answer: "Add a lockfile to pin dependency versions.", citations: [{ path: "package.json", start_line: 1, end_line: 5, evidence: "dependencies" }], limitations: [] } });
  });
  await page.getByRole("button", { name: "Demo", exact: true }).click();
  await page.getByLabel("Report question").fill("Why do I need a lockfile?");
  await page.getByRole("button", { name: "Ask about report" }).click();
  await expect(page.locator(".report-question-answer")).toContainText("Add a lockfile");
  await expect(page.locator(".report-question-answer")).toContainText("package.json:1–5");
  expect(payload.provider).toBe("openrouter");
  expect(payload.token_budget).toBe(20000);
  expect(payload.report.findings.length).toBeGreaterThan(0);
});

test("late project response cannot overwrite the selected project", async ({ page }) => {
  await setup(page);
  await page.route("**/mock-api/history/repositories", route => route.fulfill({ json: { repositories: [
    { id: "a", repo_name: "Project A", repo_url: "https://github.com/example/a" },
    { id: "b", repo_name: "Project B", repo_url: "https://github.com/example/b" }
  ] } }));
  await page.reload();
  await page.getByRole("button", { name: "EN", exact: true }).click();
  let releaseA, startedA;
  const started = new Promise(resolve => { startedA = resolve; });
  const delayed = new Promise(resolve => { releaseA = resolve; });
  const detail = name => ({ latestRun: { health_score: 82 }, findings: [], runs: [], aiReview: { summary: `Evidence belongs to Project ${name}` } });
  await page.route("**/mock-api/history/repositories/a", async route => { startedA(); await delayed; await route.fulfill({ json: detail("A") }).catch(() => {}); });
  await page.route("**/mock-api/history/repositories/b", route => route.fulfill({ json: detail("B") }));
  await page.getByRole("button", { name: "Project A https://github.com/example/a" }).click();
  await started;
  await page.getByRole("button", { name: "Project B https://github.com/example/b" }).click();
  await expect(page.locator(".project-detail-panel")).toContainText("Evidence belongs to Project B");
  releaseA();
  await page.waitForLoadState("networkidle");
  await expect(page.locator(".project-detail-panel")).toContainText("Evidence belongs to Project B");
  await expect(page.locator(".project-list-item.active")).toContainText("Project B");
});

test("history distinguishes unverified risks from resolved findings", async ({ page }) => {
  await setup(page);
  await page.route("**/mock-api/history/repositories/repo-1", route => route.fulfill({ json: {
    latestRun: { health_score: 100, resolved_findings_count: 0 }, findings: [], runs: [],
    unverified_findings: [{ fingerprint: "older", title: "Earlier security risk", severity: "high" }]
  } }));
  await page.getByRole("button", { name: "example/project https://github.com/example/project" }).click();
  await expect(page.locator(".project-detail-panel")).toContainText("Not reverified (1)");
  await expect(page.locator(".project-detail-panel")).toContainText("Earlier security risk");
});

test("previous session detail cannot replace a newly signed-in session", async ({ page }) => {
  await setup(page);
  let release, started, calls = 0;
  const requested = new Promise(resolve => { started = resolve; });
  const delayed = new Promise(resolve => { release = resolve; });
  await page.route("**/mock-api/history/repositories/repo-1", async route => {
    const old = ++calls === 1;
    if (old) { started(); await delayed; }
    await route.fulfill({ json: { latestRun: { health_score: 82 }, findings: [], runs: [], aiReview: { summary: old ? "Old session evidence" : "Current session evidence" } } }).catch(() => {});
  });
  await page.getByRole("button", { name: "example/project https://github.com/example/project" }).click();
  await requested;
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await page.getByLabel("Email", { exact: true }).fill(user.email);
  await page.getByLabel("Password", { exact: true }).fill("test-password");
  await page.locator("button.auth-primary-button").click();
  await page.getByRole("button", { name: "example/project https://github.com/example/project" }).click();
  await expect(page.locator(".project-detail-panel")).toContainText("Current session evidence");
  release();
  await page.waitForLoadState("networkidle");
  await expect(page.locator(".project-detail-panel")).toContainText("Current session evidence");
});

test("saving another finding does not cancel or falsely acknowledge an earlier save", async ({ page }) => {
  await setup(page);
  const findings = ["first", "second"].map(fingerprint => ({ fingerprint, title: fingerprint, severity: "high", recommendation: "Fix" }));
  await page.route("**/mock-api/history/repositories/repo-1", route => route.fulfill({ json: { latestRun: { health_score: 50 }, findings, runs: [] } }));
  let release, started;
  const requested = new Promise(resolve => { started = resolve; });
  const delayed = new Promise(resolve => { release = resolve; });
  await page.route("**/findings/first/feedback", async route => {
    started(); await delayed;
    await route.fulfill({ json: route.request().postDataJSON() }).catch(() => {});
  });
  await page.route("**/findings/second/feedback", route => route.fulfill({ json: route.request().postDataJSON() }));
  await page.getByRole("button", { name: "example/project https://github.com/example/project" }).click();
  const first = page.locator(".history-finding-card").filter({ has: page.getByRole("heading", { name: "first", exact: true }) });
  const second = page.locator(".history-finding-card").filter({ has: page.getByRole("heading", { name: "second", exact: true }) });
  await first.getByRole("button", { name: "Save decision" }).click();
  await requested;
  await second.getByRole("button", { name: "Save decision" }).click();
  await expect(second.getByRole("status")).toHaveText("Decision saved.");
  await expect(first.getByRole("button", { name: "Save decision" })).toBeDisabled();
  await expect(first.getByRole("status")).not.toHaveText("Decision saved.");
  release();
  await expect(first.getByRole("status")).toHaveText("Decision saved.");
});

test("history renders populated score trends and AI summaries", async ({ page }) => {
  await setup(page);
  await page.route("**/mock-api/history/repositories/repo-1", route => route.fulfill({ json: {
    latestRun: { health_score: 82 }, findings: [],
    aiReview: { summary: "## Architecture\nExisting evidence supports this summary." },
    runs: [{ id: "run-one", created_at: "2026-10-20T08:00:00Z", health_score: 82 }]
  } }));
  await page.getByRole("button", { name: "example/project https://github.com/example/project" }).click();
  await expect(page.locator(".project-detail-panel")).toContainText("Existing evidence supports this summary.");
  await expect(page.locator(".project-detail-panel")).toContainText("82");
});

test("hydrating a URL session does not abort the first history load", async ({ page }) => {
  await page.route("**/mock-auth/auth/v1/user", async route => {
    await new Promise(resolve => setTimeout(resolve, 50));
    await route.fulfill({ json: user });
  });
  await page.route("**/mock-api/history/repositories", async route => {
    await new Promise(resolve => setTimeout(resolve, 250));
    await route.fulfill({ json: { repositories: [{ id: "repo-1", repo_name: "example/project", repo_url: "https://github.com/example/project" }] } });
  });
  await page.goto("/#access_token=token&refresh_token=refresh&expires_in=3600&token_type=bearer");
  await expect(page.getByRole("button", { name: "Review repository" })).toBeVisible();
  await expect(page.getByRole("button", { name: /example\/project/ })).toBeVisible();
});

test("an expired session without a refresh token returns to sign-in", async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("repo-review-auth-session", JSON.stringify({ access_token: "expired", expires_at: 1 }));
  });
  await page.goto("/");
  await expect(page.locator(".auth-card")).toBeVisible();
  await expect(page.getByRole("button", { name: "Review repository" })).toHaveCount(0);
});
