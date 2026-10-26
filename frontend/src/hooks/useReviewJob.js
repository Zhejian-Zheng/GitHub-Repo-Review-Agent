import { useEffect, useRef, useState } from "react";
import { clearStoredSession, getValidSession } from "../authClient";
import { submitReviewJob, waitForReviewJob, cancelReviewJob, askReportQuestion, normalizeTokenBudget, cancellationTargetsCurrentJob } from "../reviewJobsClient";
import { buildDemoReport } from "../demoReport";
import { renderStaticMarkdown } from "../reportMarkdown";

function translateJobStatus(status, isChinese) {
  const labels = {
    queued: isChinese ? "排队中" : "queued",
    running: isChinese ? "扫描中" : "running",
    completed: isChinese ? "已完成" : "completed",
    failed: isChinese ? "失败" : "failed",
    cancelled: isChinese ? "已取消" : "cancelled"
  };
  return labels[status] || status;
}

export function storedPendingJob() {
  try { return JSON.parse(sessionStorage.getItem("repo-review-pending-job") || "null"); }
  catch { return null; }
}

export function useReviewJob({ form, authSession, setAuthSession, ensureFreshSession,
  isGuestMode, isChinese, runPhases, loadProjectList }) {
  const [status, setStatus] = useState("Ready");
  const [isRunning, setIsRunning] = useState(false);
  const [markdown, setMarkdown] = useState("");
  const [report, setReport] = useState(null);
  const [progressStep, setProgressStep] = useState(0);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const reportRef = useRef(null);
  const reviewController = useRef(null);
  const [reportJobId, setReportJobId] = useState(null);
  const [isCancelling, setIsCancelling] = useState(false);
  const [pendingJob, setPendingJob] = useState(storedPendingJob);
  const pendingJobRef = useRef(pendingJob);
  const cancelRequestRef = useRef(0);
  const rememberJob = (job) => {
    pendingJobRef.current = job;
    setPendingJob(job);
    if (job) sessionStorage.setItem("repo-review-pending-job", JSON.stringify(job));
    else sessionStorage.removeItem("repo-review-pending-job");
  };
  useEffect(() => () => reviewController.current?.abort(), []);

  useEffect(() => {
    if (!isRunning) return undefined;
    const interval = window.setInterval(() => {
      setElapsedSeconds((current) => current + 1);
    }, 1000);
    return () => window.clearInterval(interval);
  }, [isRunning]);

  const runReview = async (event, resume = false) => {
    event.preventDefault();
    reviewController.current?.abort();
    const controller = new AbortController();
    reviewController.current = controller;
    setIsRunning(true);
    setProgressStep(0);
    setElapsedSeconds(0);
    setStatus(isChinese ? "评审已开始，正在连接后端..." : "Review started. Connecting to backend...");
    setMarkdown("");
    setReport(null);
    setReportJobId(null);
    const hadSession = Boolean(authSession?.access_token);
    const session = await ensureFreshSession(authSession, { signal: controller.signal });
    if (controller.signal.aborted) {
      setIsRunning(false);
      setStatus(isChinese ? "已停止跟踪。" : "Tracking stopped.");
      return;
    }
    if (hadSession && !session?.access_token) {
      setIsRunning(false);
      setStatus(isChinese ? "登录已过期，请重新登录后再保存历史。" : "Session expired. Sign in again to save history.");
      return;
    }

    const payload = {
      ...form,
      ai_model: form.ai_model.trim() || null,
      ai_token_budget: normalizeTokenBudget(form.ai_token_budget),
      save_history: Boolean(session?.access_token),
      history_repo_url: form.target.trim() || null
    };

    try {
      const job = resume && pendingJob
        ? { job_id: pendingJob.id }
        : await submitReviewJob(payload, session?.access_token, { signal: controller.signal });
      rememberJob({ id: job.job_id, userId: session?.user?.id || null, form });
      let pollingSession = session;
      setStatus(
        isChinese
          ? `扫描任务已提交：${job.job_id.slice(0, 8)}。正在排队...`
          : `Review job ${job.job_id.slice(0, 8)} submitted. Waiting for a worker...`
      );
      const data = await waitForReviewJob(job.job_id, session?.access_token, {
        signal: controller.signal,
        getAccessToken: async (signal) => {
          if (!pollingSession) return undefined;
          pollingSession = await getValidSession(pollingSession, { signal });
          if (!pollingSession?.access_token) {
            if (signal?.aborted) throw new DOMException("Review tracking stopped.", "AbortError");
            clearStoredSession();
            setAuthSession(null);
            throw new Error("Session expired. Sign in again to resume tracking.");
          }
          if (!controller.signal.aborted) setAuthSession(pollingSession);
          return pollingSession.access_token;
        },
        onUpdate: (nextJob) => {
          const index = runPhases.findIndex((phase) => phase.key === nextJob.phase);
          if (index >= 0) setProgressStep(index);
          if (["completed", "failed", "cancelled"].includes(nextJob.status)) rememberJob(null);
          const shortId = nextJob.job_id.slice(0, 8);
          setStatus(
            isChinese
              ? `扫描任务 ${shortId}：${translateJobStatus(nextJob.status, true)}。`
              : `Review job ${shortId}: ${translateJobStatus(nextJob.status, false)}.`
          );
        }
      });

      setReportJobId(job.job_id);
      setMarkdown(data.markdown || "");
      setReport(data.report || null);
      setStatus(
        data.history
          ? isChinese
            ? `评审完成，历史已保存。新增 ${data.history.new_findings_count} 个问题，已解决 ${data.history.resolved_findings_count} 个问题，未复核 ${data.history.unverified_findings_count || 0} 个问题。`
            : `Review complete. History saved with ${data.history.new_findings_count} new, ${data.history.resolved_findings_count} resolved and ${data.history.unverified_findings_count || 0} not reverified findings.`
          : "Review complete."
      );
      if (data.history && session?.access_token) {
        loadProjectList(session.access_token, { silent: true });
      }
      window.requestAnimationFrame(() => {
        reportRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    } catch (error) {
      const guestMessage =
        isGuestMode && /sign in/i.test(error.message)
          ? isChinese
            ? "游客模式可以查看 Demo。当前后端要求登录后才能运行真实扫描。"
            : "Guest mode can view the demo. This backend requires sign-in for live reviews."
          : error.message;
      setStatus(error.name === "AbortError"
        ? (isChinese ? "已停止跟踪；后台任务可能仍在运行，可恢复跟踪。" : "Tracking stopped. The backend job may still be running; you can resume tracking.")
        : `Review failed: ${guestMessage}`);
    } finally {
      setIsRunning(false);
    }
  };

  const cancelReview = async () => {
    const jobToCancel = pendingJobRef.current;
    if (!jobToCancel || isCancelling) return;
    const controller = reviewController.current;
    const cancelRequest = ++cancelRequestRef.current;
    setIsCancelling(true);
    try {
      const session = await ensureFreshSession();
      if (!session?.access_token) throw new Error("Sign in to cancel your review.");
      const job = await cancelReviewJob(jobToCancel.id, session.access_token);
      const current = cancellationTargetsCurrentJob(
        jobToCancel.id, pendingJobRef.current, controller, reviewController.current);
      if (!current) return;
      if (job.status === "cancelled") {
        reviewController.current?.abort();
        rememberJob(null);
        setIsRunning(false);
        // The aborted tracker settles first; show the server's confirmed result.
        setTimeout(() => setStatus(isChinese ? "评审已取消。" : "Review cancelled."), 0);
      } else {
        setStatus(`Review ${job.status}.`);
      }
    } catch (error) {
      if (cancellationTargetsCurrentJob(
          jobToCancel.id, pendingJobRef.current, controller, reviewController.current)) {
        setStatus(error.message);
      }
    } finally {
      if (cancelRequest === cancelRequestRef.current) setIsCancelling(false);
    }
  };

  const askQuestion = async (question) => {
    const session = await ensureFreshSession();
    return askReportQuestion({ ...(reportJobId ? { job_id: reportJobId } : { report }), question,
      provider: form.ai_provider, model: form.ai_model || null, language: form.report_language,
      token_budget: Math.min(20000, normalizeTokenBudget(form.ai_token_budget)) }, session?.access_token);
  };

  const copyReport = async () => {
    if (!markdown) return;
    await navigator.clipboard.writeText(markdown);
    setStatus("Report copied.");
  };

  const downloadReport = () => {
    if (!markdown) return;
    const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
    link.href = url;
    link.download = `repo-review-${stamp}.md`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    setStatus("Report downloaded.");
  };

  const closeReport = () => {
    setMarkdown("");
    setReport(null);
    setStatus("Report closed.");
  };

  const loadDemoReport = () => {
    setReportJobId(null);
    const demoReport = buildDemoReport(form.report_language);
    setReport(demoReport);
    setMarkdown(renderStaticMarkdown(demoReport, form.report_language));
    setStatus("Demo report loaded.");
    window.requestAnimationFrame(() => {
      reportRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  };

  const resetReview = () => {
    reviewController.current?.abort();
    rememberJob(null);
    setReport(null); setMarkdown(""); setReportJobId(null);
  };
  return { status, isRunning, markdown, report, progressStep, elapsedSeconds, reportRef,
    reviewController, pendingJob, isCancelling, runReview, cancelReview, askQuestion,
    copyReport, downloadReport, closeReport, loadDemoReport, resetReview };
}
