import { test, expect } from "@playwright/test";

// Deliberately ignore abort at the transport boundary. Hook identity guards must
// protect state even when dependencies have already completed or cannot cancel.
test.beforeEach(async ({ page }) => {
  await page.route("**/src/reviewJobsClient*", route => route.fulfill({
    contentType: "application/javascript", body: `
      export const normalizeTokenBudget = value => value;
      export const cancellationTargetsCurrentJob = () => false;
      export const cancelReviewJob = () => {};
      export const askReportQuestion = () => {};
      export function submitReviewJob() {
        const h = window.reviewHarness, pending = h.deferred();
        h.submissions.push(pending);
        return pending.promise;
      }
      export function waitForReviewJob(id, token, options) {
        const h = window.reviewHarness, pending = h.deferred();
        h.polls.push({ ...pending, id, options });
        return pending.promise;
      }
    `,
  }));
  await page.goto("/e2e/fixtures/review-hook.html");
  await page.evaluate(async () => (await import("/e2e/fixtures/review-hook.jsx")).mount());
  await expect(page.getByRole("button", { name: "Run", exact: true })).toBeVisible();
});

const state = page => page.locator("output").textContent().then(JSON.parse);
async function startPolling(page, id) {
  await page.getByRole("button", { name: "Run", exact: true }).click();
  await page.evaluate(() => reviewHarness.sessions.at(-1).resolve(reviewHarness.session));
  await expect.poll(() => page.evaluate(() => reviewHarness.submissions.length)).toBeGreaterThan(0);
  await page.evaluate(id => reviewHarness.submissions.at(-1).resolve({ job_id: id }), id);
  await expect.poll(() => page.evaluate(() => reviewHarness.polls.at(-1)?.id)).toBe(id);
}

for (const outcome of ["resolve", "reject"]) {
  test(`late session ${outcome} after reset cannot affect a new run`, async ({ page }) => {
    await page.getByRole("button", { name: "Run", exact: true }).click();
    await page.getByRole("button", { name: "Reset", exact: true }).click();
    expect((await state(page)).running).toBe(false);
    await page.getByRole("button", { name: "Run", exact: true }).click();
    await page.evaluate(outcome => {
      const h = reviewHarness;
      h.sessions[0][outcome](outcome === "reject" ? new Error("Old refresh failed") : h.session);
    }, outcome);
    await page.waitForTimeout(50);
    expect(await state(page)).toMatchObject({ running: true, status: "Review started. Connecting to backend...", pending: null });
    expect(await page.evaluate(() => reviewHarness.errors)).toEqual([]);
    expect(await page.evaluate(() => reviewHarness.submissions.length)).toBe(0);
  });
}

test("current refresh rejection always clears loading", async ({ page }) => {
  await page.getByRole("button", { name: "Run", exact: true }).click();
  await page.evaluate(() => reviewHarness.sessions[0].reject(new Error("Refresh failed")));
  await expect.poll(() => state(page)).toMatchObject({ running: false, status: "Review failed: Refresh failed" });
  expect(await page.evaluate(() => reviewHarness.errors)).toEqual([]);
});

for (const outcome of ["resolve", "reject"]) {
  test(`old poll ${outcome} and phase update cannot overwrite a new run`, async ({ page }) => {
    await startPolling(page, "old-job");
    await page.getByRole("button", { name: "Reset", exact: true }).click();
    await startPolling(page, "new-job");
    await page.evaluate(outcome => {
      const old = reviewHarness.polls[0];
      old.options.onUpdate({ job_id: "old-job", status: "completed", phase: "analyzing" });
      old[outcome](outcome === "reject" ? new Error("Old job failed") : {
        report: { repo_name: "old" }, history: { new_findings_count: 1 }, markdown: "old report",
      });
    }, outcome);
    await page.waitForTimeout(50);
    expect(await state(page)).toMatchObject({ running: true, report: null, pending: { id: "new-job" },
      status: "Review job new-job submitted. Waiting for a worker..." });
    expect(await page.evaluate(() => reviewHarness.history)).toEqual([]);
    await page.evaluate(() => reviewHarness.polls[1].resolve({ report: { repo_name: "new" } }));
    await expect.poll(() => state(page)).toMatchObject({ running: false, report: { repo_name: "new" } });
  });
}

test("late submit cannot restore pending state after reset", async ({ page }) => {
  await page.getByRole("button", { name: "Run", exact: true }).click();
  await page.evaluate(() => reviewHarness.sessions[0].resolve(reviewHarness.session));
  await expect.poll(() => page.evaluate(() => reviewHarness.submissions.length)).toBe(1);
  await page.getByRole("button", { name: "Reset", exact: true }).click();
  await page.evaluate(() => reviewHarness.submissions[0].resolve({ job_id: "old-job" }));
  await page.waitForTimeout(50);
  expect(await state(page)).toMatchObject({ running: false, report: null, pending: null });
  expect(await page.evaluate(() => reviewHarness.polls.length)).toBe(0);
});

test("a token continuation cannot update auth after reset", async ({ page }) => {
  await startPolling(page, "old-job");
  const outcome = await page.evaluate(async () => {
    const h = reviewHarness;
    const pending = h.polls[0].options.getAccessToken(new AbortController().signal);
    h.review.resetReview();
    try { await pending; return "accepted"; }
    catch (error) { return error.name; }
  });
  expect(outcome).toBe("AbortError");
  expect(await page.evaluate(() => reviewHarness.auth)).toEqual([]);
});

test("expired initial session clears loading without submitting", async ({ page }) => {
  await page.getByRole("button", { name: "Run", exact: true }).click();
  await page.evaluate(() => reviewHarness.sessions[0].resolve(null));
  await expect.poll(() => state(page)).toMatchObject({ running: false,
    status: "Session expired. Sign in again to save history." });
  expect(await page.evaluate(() => reviewHarness.submissions.length)).toBe(0);
});
