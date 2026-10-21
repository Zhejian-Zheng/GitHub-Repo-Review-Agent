import { friendlyAuthError } from "./authMessages";
import React, { useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { ArrowRight, ChevronDown, FileText, RefreshCw, RotateCcw } from "lucide-react";
import { isAuthConfigured, signOut } from "./authClient";
import { DEFAULT_TARGET, MODEL_OPTIONS, progressCopy } from "./config";

import { AuthGate, AuthPanel, GuestPanel } from "./features/Auth";
import { ProjectHistoryWorkspace } from "./features/History";
import { ReportQuestionForm } from "./features/Questions";
import { ReportView, RunProgress } from "./features/Report";
import { useAuthSession } from "./hooks/useAuthSession";
import { useProjectHistory } from "./hooks/useProjectHistory";
import { storedPendingJob, useReviewJob } from "./hooks/useReviewJob";
import "./styles.css";

function App() {
  const [form, setForm] = useState(() => storedPendingJob()?.form || ({
    target: DEFAULT_TARGET,
    mode: "agent",
    ai_provider: "openrouter",
    ai_model: "openrouter/auto",
    report_language: "zh-CN",
    ai_token_budget: 20000,
    vulnerability_scan: false
  }));
  const selectedModelValue = useMemo(() => {
    const option = MODEL_OPTIONS.find(
      (item) => item.provider === form.ai_provider && item.model === form.ai_model
    );
    return option?.value ?? MODEL_OPTIONS[0].value;
  }, [form.ai_model, form.ai_provider]);
  const isChinese = form.report_language === "zh-CN";
  const runPhases = useMemo(() => {
    const phases = progressCopy[form.report_language] ?? progressCopy.en;
    return phases.filter((phase) => phase.key !== "ai" || form.ai_provider !== "none");
  }, [form.ai_provider, form.report_language]);

  const { authSession, setAuthSession, isGuestMode, setIsGuestMode, authStatus,
    handleSignIn, handleSignUp, handleGuestContinue, ensureFreshSession, endSession } = useAuthSession(isChinese);
  const { repositories, selectedRepository, projectDetail, isHistoryLoading, historyError,
    loadProjectList, openProjectDetail, updateFeedback, resetHistory } = useProjectHistory(authSession, ensureFreshSession);
  const { status, isRunning, markdown, report, progressStep, elapsedSeconds, reportRef,
    reviewController, pendingJob, isCancelling, runReview, cancelReview, askQuestion,
    copyReport, downloadReport, closeReport, loadDemoReport, resetReview } = useReviewJob({
      form, authSession, setAuthSession, ensureFreshSession, isGuestMode, isChinese, runPhases, loadProjectList
    });
  const handleSignOut = async () => {
    resetHistory(); resetReview();
    const token = authSession?.access_token;
    endSession();
    try { await signOut(token); } catch { /* Local session is already cleared. */ }
  };

  const activeRunPhase = runPhases[progressStep] ?? runPhases[0];
  const shouldShowAuthGate = isAuthConfigured() && !authSession?.access_token && !isGuestMode;

  const updateField = (event) => {
    const { name, value } = event.target;
    setForm((current) => ({ ...current, [name]: value }));
  };

  const updateModel = (event) => {
    const option = MODEL_OPTIONS.find((item) => item.value === event.target.value);
    if (!option) return;
    setForm((current) => ({
      ...current,
      ai_provider: option.provider,
      ai_model: option.model
    }));
  };

  const setLanguage = (reportLanguage) => {
    setForm((current) => ({ ...current, report_language: reportLanguage }));
  };

  const authErrorMessage = (message) => friendlyAuthError(message, isChinese);

  if (shouldShowAuthGate) {
    return (
      <AuthGate
        language={form.report_language}
        status={authStatus}
        onSignIn={handleSignIn}
        onSignUp={handleSignUp}
        onGuestContinue={handleGuestContinue}
        onSetLanguage={setLanguage}
        formatError={authErrorMessage}
      />
    );
  }

  return (
    <main className="min-h-screen bg-white text-ink">
      <section className="chat-home">
        <header className="chat-topbar">
          <button className="brand-menu" type="button" aria-label="RepoGPT menu">
            <span>RepoGPT</span>
          </button>

          <div className="top-actions">
            {authSession?.access_token ? (
              <AuthPanel
                configured={isAuthConfigured()}
                session={authSession}
                status={authStatus}
                language={form.report_language}
                onSignIn={handleSignIn}
                onSignUp={handleSignUp}
                onSignOut={handleSignOut}
                formatError={authErrorMessage}
              />
            ) : isGuestMode ? (
              <GuestPanel language={form.report_language} onSignIn={() => setIsGuestMode(false)} />
            ) : (
              <AuthPanel
                configured={isAuthConfigured()}
                session={authSession}
                status={authStatus}
                language={form.report_language}
                onSignIn={handleSignIn}
                onSignUp={handleSignUp}
                onSignOut={handleSignOut}
                formatError={authErrorMessage}
              />
            )}

            <label className="model-select" aria-label="Model">
              <select value={selectedModelValue} onChange={updateModel}>
                {MODEL_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <ChevronDown size={16} aria-hidden="true" />
            </label>

            <div className="language-toggle" role="group" aria-label="Report language">
              <button
                className={isChinese ? "active" : ""}
                type="button"
                onClick={() => setLanguage("zh-CN")}
                aria-pressed={isChinese}
              >
                中文
              </button>
              <button
                className={!isChinese ? "active" : ""}
                type="button"
                onClick={() => setLanguage("en")}
                aria-pressed={!isChinese}
              >
                EN
              </button>
            </div>
          </div>
        </header>

        <form className="prompt-stage" onSubmit={runReview}>
          <div className="prompt-copy">
            <h1>{isChinese ? "你想看看哪个仓库" : "Put the repo you want to know"}</h1>
          </div>

          <div className={`prompt-bar ${isRunning ? "running" : ""}`} aria-busy={isRunning}>
            <input
              className="repo-input"
              name="target"
              value={form.target}
              onChange={updateField}
              placeholder="put the repo you want to know"
              aria-label="GitHub repository URL"
              disabled={isRunning}
            />
            {isRunning ? (
              <div className="prompt-running-indicator" aria-live="polite">
                <RotateCcw size={16} className="animate-spin" aria-hidden="true" />
                <span>{isChinese ? "正在评审" : "Reviewing"}</span>
              </div>
            ) : null}
            <button
              className="icon-button send"
              type="submit"
              disabled={isRunning}
              aria-label="Review repository"
            >
              {isRunning ? (
                <RotateCcw size={21} className="animate-spin" aria-hidden="true" />
              ) : (
                <ArrowRight size={22} strokeWidth={2.4} aria-hidden="true" />
              )}
            </button>
          </div>

          <div className="review-options">
            <label>{isChinese ? "AI Token 上限" : "AI token budget"}
              <input aria-label="AI token budget" type="number" min="256" max="200000" step="1"
                value={form.ai_token_budget || 20000} disabled={isRunning}
                onChange={event => setForm(current => ({ ...current, ai_token_budget: Number(event.target.value) }))} />
            </label>
            <label><input type="checkbox" checked={Boolean(form.vulnerability_scan)} disabled={isRunning}
              onChange={event => setForm(current => ({ ...current, vulnerability_scan: event.target.checked }))} />
              {isChinese ? "依赖漏洞扫描" : "Scan dependency vulnerabilities"}
            </label>
          </div>

          {isRunning ? (
            <RunProgress
              phases={runPhases}
              activeIndex={progressStep}
              elapsedSeconds={elapsedSeconds}
              language={form.report_language}
            />
          ) : null}

          <div className="home-actions">
            {isRunning ? (
              <button className="demo-button" type="button" onClick={() => reviewController.current?.abort()}>
                {isChinese ? "停止跟踪" : "Stop tracking"}
              </button>
            ) : pendingJob && pendingJob.userId === (authSession?.user?.id || null) ? (
              <button className="demo-button" type="button" onClick={(event) => runReview(event, true)}>
                {isChinese ? "恢复任务跟踪" : "Resume tracking"}
              </button>
            ) : null}
            {pendingJob && authSession?.access_token && pendingJob.userId === authSession?.user?.id ? (
              <button className="demo-button" type="button" disabled={isCancelling} onClick={cancelReview}>
                {isChinese ? "取消评审" : "Cancel review"}
              </button>
            ) : null}
            <button className="demo-button" type="button" onClick={loadDemoReport}>
              <FileText size={17} aria-hidden="true" />
              Demo
            </button>
            {authSession?.access_token ? (
              <button
                className="demo-button"
                type="button"
                onClick={() => loadProjectList(authSession.access_token)}
              >
                <RefreshCw size={17} aria-hidden="true" />
                {isChinese ? "刷新历史" : "Refresh history"}
              </button>
            ) : null}
          </div>

          <p className="home-status" aria-live="polite">
            {isRunning && activeRunPhase
              ? isChinese
                ? `当前状态：${activeRunPhase.label}，已运行 ${elapsedSeconds} 秒。`
                : `Current status: ${activeRunPhase.label}, ${elapsedSeconds}s elapsed.`
              : status}
          </p>
        </form>
      </section>

      {authSession?.access_token ? (
        <ProjectHistoryWorkspace
          repositories={repositories}
          selectedRepository={selectedRepository}
          detail={projectDetail}
          isLoading={isHistoryLoading}
          error={historyError}
          language={form.report_language}
          onOpenProject={openProjectDetail}
          onFeedback={updateFeedback}
          onRefresh={() => loadProjectList(authSession.access_token)}
        />
      ) : null}

      {markdown ? (
        <div className="report-shell">
          <ReportView
            ref={reportRef}
            report={report}
            markdown={markdown}
            language={form.report_language}
            onCopy={copyReport}
            onDownload={downloadReport}
            onClose={closeReport}
          />
          {report ? <ReportQuestionForm language={form.report_language} onAsk={askQuestion} provider={form.ai_provider} /> : null}
        </div>
      ) : null}
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
