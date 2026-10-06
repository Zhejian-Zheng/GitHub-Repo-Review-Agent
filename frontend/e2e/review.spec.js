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
