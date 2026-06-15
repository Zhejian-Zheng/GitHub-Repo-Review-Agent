import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  Clipboard,
  Download,
  FileText,
  GitBranch,
  LogIn,
  LogOut,
  RefreshCw,
  RotateCcw,
  TrendingUp,
  UserRound,
  X
} from "lucide-react";
import {
  authConfig,
  clearStoredSession,
  consumeSessionFromUrl,
  getCurrentUser,
  getValidSession,
  isAuthConfigured,
  loadStoredSession,
  saveStoredSession,
  signInWithPassword,
  signOut,
  signUpWithPassword
} from "./authClient";
import { DEFAULT_TARGET, MODEL_OPTIONS, progressCopy } from "./config";
import { buildDemoReport } from "./demoReport";
import { fetchProjectDetail, fetchRepositories } from "./historyClient";
import { renderStaticMarkdown } from "./reportMarkdown";
import { reportCopy } from "./reportCopy";
import "./styles.css";

function App() {
  const [form, setForm] = useState({
    target: DEFAULT_TARGET,
    mode: "agent",
    ai_provider: "openrouter",
    ai_model: "openrouter/auto",
    report_language: "zh-CN"
  });
  const [status, setStatus] = useState("Ready");
  const [isRunning, setIsRunning] = useState(false);
  const [markdown, setMarkdown] = useState("");
  const [report, setReport] = useState(null);
  const [progressStep, setProgressStep] = useState(0);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [authSession, setAuthSession] = useState(() => loadStoredSession());
  const [authStatus, setAuthStatus] = useState("");
  const [repositories, setRepositories] = useState([]);
  const [selectedRepository, setSelectedRepository] = useState(null);
  const [projectDetail, setProjectDetail] = useState(null);
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const reportRef = useRef(null);

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

  useEffect(() => {
    const urlSession = consumeSessionFromUrl();
    const session = urlSession || loadStoredSession();
    if (!session?.access_token) return undefined;

    setAuthSession(session);
    let isMounted = true;
    getValidSession(session)
      .then((validSession) => {
        if (!validSession?.access_token) {
          throw new Error(isChinese ? "登录已过期，请重新登录。" : "Session expired. Sign in again.");
        }
        return getCurrentUser(validSession.access_token).then((user) => ({ validSession, user }));
      })
      .then((user) => {
        if (!isMounted) return;
        const nextSession = { ...user.validSession, user: user.user };
        saveStoredSession(nextSession);
        setAuthSession(nextSession);
      })
      .catch((error) => {
        if (!isMounted) return;
        clearStoredSession();
        setAuthSession(null);
        setAuthStatus(error.message);
      });
    return () => {
      isMounted = false;
    };
  }, []);

  useEffect(() => {
    if (!authSession?.access_token) {
      setRepositories([]);
      setSelectedRepository(null);
      setProjectDetail(null);
      return undefined;
    }

    let isMounted = true;
    loadProjectList(authSession.access_token, { silent: true, isMountedRef: () => isMounted });
    return () => {
      isMounted = false;
    };
  }, [authSession?.access_token]);

  useEffect(() => {
    if (!isRunning) return undefined;
    const interval = window.setInterval(() => {
      setProgressStep((current) => Math.min(current + 1, runPhases.length - 1));
    }, 1600);
    return () => window.clearInterval(interval);
  }, [isRunning, runPhases.length]);

  useEffect(() => {
    if (!isRunning) return undefined;
    const interval = window.setInterval(() => {
      setElapsedSeconds((current) => current + 1);
    }, 1000);
    return () => window.clearInterval(interval);
  }, [isRunning]);

  const activeRunPhase = runPhases[progressStep] ?? runPhases[0];

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

  const handleSignIn = async ({ email, password }) => {
    setAuthStatus(isChinese ? "正在登录..." : "Signing in...");
    const session = await signInWithPassword(email, password);
    const user = session.user || (await getCurrentUser(session.access_token));
    const nextSession = { ...session, user };
    saveStoredSession(nextSession);
    setAuthSession(nextSession);
    setAuthStatus(isChinese ? "已登录，后续评审会保存历史。" : "Signed in. Review history will be saved.");
  };

  const handleSignUp = async ({ email, password }) => {
    setAuthStatus(isChinese ? "正在创建账号..." : "Creating account...");
    const session = await signUpWithPassword(email, password);
    if (session.pending_confirmation) {
      setAuthStatus(isChinese ? "请查看邮箱并确认账号。" : "Check your email to confirm your account.");
      return;
    }
    const user = session.user || (await getCurrentUser(session.access_token));
    const nextSession = { ...session, user };
    saveStoredSession(nextSession);
    setAuthSession(nextSession);
    setAuthStatus(isChinese ? "账号已创建，后续评审会保存历史。" : "Account created. Review history will be saved.");
  };

  const handleSignOut = async () => {
    try {
      await signOut(authSession?.access_token);
    } finally {
      setAuthSession(null);
      setRepositories([]);
      setSelectedRepository(null);
      setProjectDetail(null);
      setAuthStatus(isChinese ? "已退出登录。" : "Signed out.");
    }
  };

  const ensureFreshSession = async (session = authSession) => {
    if (!session?.access_token) return null;
    try {
      const nextSession = await getValidSession(session);
      if (!nextSession?.access_token) {
        setAuthSession(null);
        setRepositories([]);
        setSelectedRepository(null);
        setProjectDetail(null);
        setAuthStatus(isChinese ? "登录已过期，请重新登录。" : "Session expired. Sign in again.");
        return null;
      }
      if (nextSession.access_token !== session.access_token) {
        const user = nextSession.user || session.user || (await getCurrentUser(nextSession.access_token));
        const refreshedSession = { ...nextSession, user };
        saveStoredSession(refreshedSession);
        setAuthSession(refreshedSession);
        return refreshedSession;
      }
      return nextSession;
    } catch (error) {
      clearStoredSession();
      setAuthSession(null);
      setRepositories([]);
      setSelectedRepository(null);
      setProjectDetail(null);
      setAuthStatus(error.message);
      return null;
    }
  };

  const loadProjectList = async (
    accessToken = authSession?.access_token,
    { silent = false, isMountedRef = () => true } = {}
  ) => {
    const session = await ensureFreshSession(
      accessToken === authSession?.access_token ? authSession : { access_token: accessToken }
    );
    if (!session?.access_token) return;
    if (!silent) {
      setIsHistoryLoading(true);
    }
    setHistoryError("");
    try {
      const nextRepositories = await fetchRepositories(session.access_token);
      if (!isMountedRef()) return;
      setRepositories(nextRepositories);
    } catch (error) {
      if (!isMountedRef()) return;
      setHistoryError(error.message);
    } finally {
      if (!silent && isMountedRef()) {
        setIsHistoryLoading(false);
      }
    }
  };

  const openProjectDetail = async (repository) => {
    if (!authSession?.access_token) return;
    const session = await ensureFreshSession();
    if (!session?.access_token) return;
    setSelectedRepository(repository);
    setProjectDetail(null);
    setHistoryError("");
    setIsHistoryLoading(true);
    try {
      const detail = await fetchProjectDetail(repository.id, session.access_token);
      setProjectDetail(detail);
      window.requestAnimationFrame(() => {
        document.getElementById("project-detail")?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    } catch (error) {
      setHistoryError(error.message);
    } finally {
      setIsHistoryLoading(false);
    }
  };

  const runReview = async (event) => {
    event.preventDefault();
    setIsRunning(true);
    setProgressStep(0);
    setElapsedSeconds(0);
    setStatus(isChinese ? "评审已开始，正在连接后端..." : "Review started. Connecting to backend...");
    setMarkdown("");
    setReport(null);
    const hadSession = Boolean(authSession?.access_token);
    const session = await ensureFreshSession();
    if (hadSession && !session?.access_token) {
      setIsRunning(false);
      setStatus(isChinese ? "登录已过期，请重新登录后再保存历史。" : "Session expired. Sign in again to save history.");
      return;
    }

    const payload = {
      ...form,
      ai_model: form.ai_model.trim() || null,
      save_history: Boolean(session?.access_token),
      history_repo_url: form.target.trim() || null
    };

    try {
      const headers = { "Content-Type": "application/json" };
      if (authConfig.apiToken) {
        headers["X-Repo-Review-Token"] = authConfig.apiToken;
      }
      if (session?.access_token) {
        headers.Authorization = `Bearer ${session.access_token}`;
      }
      const response = await fetch("/review", {
        method: "POST",
        headers,
        body: JSON.stringify(payload)
      });
      const responseText = await response.text();
      let data = null;
      if (responseText) {
        try {
          data = JSON.parse(responseText);
        } catch (error) {
          throw new Error(
            "Review backend did not return JSON. Start the backend on port 8000, then try again."
          );
        }
      }
      if (!response.ok) {
        throw new Error(data?.detail || `Review backend returned HTTP ${response.status}.`);
      }
      if (!data) {
        throw new Error("Review backend returned an empty response.");
      }

      setMarkdown(data.markdown || "");
      setReport(data.report || null);
      setStatus(
        data.history
          ? isChinese
            ? `评审完成，历史已保存。新增 ${data.history.new_findings_count} 个问题，已解决 ${data.history.resolved_findings_count} 个问题。`
            : `Review complete. History saved with ${data.history.new_findings_count} new and ${data.history.resolved_findings_count} resolved findings.`
          : "Review complete."
      );
      if (data.history && session?.access_token) {
        loadProjectList(session.access_token, { silent: true });
      }
      window.requestAnimationFrame(() => {
        reportRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    } catch (error) {
      setStatus(`Review failed: ${error.message}`);
    } finally {
      setIsRunning(false);
    }
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
    const demoReport = buildDemoReport(form.report_language);
    setReport(demoReport);
    setMarkdown(renderStaticMarkdown(demoReport, form.report_language));
    setStatus("Demo report loaded.");
    window.requestAnimationFrame(() => {
      reportRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  };

  return (
    <main className="min-h-screen bg-white text-ink">
      <section className="chat-home">
        <header className="chat-topbar">
          <button className="brand-menu" type="button" aria-label="RepoGPT menu">
            <span>RepoGPT</span>
          </button>

          <div className="top-actions">
            <AuthPanel
              configured={isAuthConfigured()}
              session={authSession}
              status={authStatus}
              language={form.report_language}
              onSignIn={handleSignIn}
              onSignUp={handleSignUp}
              onSignOut={handleSignOut}
            />

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

          {isRunning ? (
            <RunProgress
              phases={runPhases}
              activeIndex={progressStep}
              elapsedSeconds={elapsedSeconds}
              language={form.report_language}
            />
          ) : null}

          <div className="home-actions">
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
        </div>
      ) : null}
    </main>
  );
}

function AuthPanel({ configured, session, status, language, onSignIn, onSignUp, onSignOut }) {
  const [mode, setMode] = useState("sign-in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");
  const isChinese = language === "zh-CN";
  const userEmail = session?.user?.email;

  if (!configured) {
    return (
      <div className="auth-compact unavailable" title="Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY">
        <UserRound size={16} aria-hidden="true" />
        <span>{isChinese ? "未配置登录" : "Auth off"}</span>
      </div>
    );
  }

  if (session?.access_token) {
    return (
      <div className="auth-compact signed-in">
        <UserRound size={16} aria-hidden="true" />
        <span title={userEmail || "Signed in"}>{userEmail || (isChinese ? "已登录" : "Signed in")}</span>
        <button className="auth-icon-button" type="button" onClick={onSignOut} aria-label="Sign out">
          <LogOut size={16} aria-hidden="true" />
        </button>
      </div>
    );
  }

  const submitAuth = async (event) => {
    event.preventDefault();
    setError("");
    setIsSubmitting(true);
    try {
      if (mode === "sign-up") {
        await onSignUp({ email, password });
      } else {
        await onSignIn({ email, password });
      }
      setPassword("");
    } catch (authError) {
      setError(authError.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <form className="auth-panel" onSubmit={submitAuth}>
      <div className="auth-tabs" role="tablist" aria-label="Authentication mode">
        <button
          className={mode === "sign-in" ? "active" : ""}
          type="button"
          onClick={() => setMode("sign-in")}
        >
          {isChinese ? "登录" : "Sign in"}
        </button>
        <button
          className={mode === "sign-up" ? "active" : ""}
          type="button"
          onClick={() => setMode("sign-up")}
        >
          {isChinese ? "注册" : "Sign up"}
        </button>
      </div>
      <input
        type="email"
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        placeholder="email"
        aria-label="Email"
        required
      />
      <input
        type="password"
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        placeholder="password"
        aria-label="Password"
        minLength={6}
        required
      />
      <button className="auth-submit" type="submit" disabled={isSubmitting}>
        {isSubmitting ? (
          <RotateCcw size={15} className="animate-spin" aria-hidden="true" />
        ) : (
          <LogIn size={15} aria-hidden="true" />
        )}
        {mode === "sign-up" ? (isChinese ? "注册" : "Join") : isChinese ? "登录" : "Login"}
      </button>
      {error || status ? <p className={error ? "auth-error" : "auth-status"}>{error || status}</p> : null}
    </form>
  );
}

function ProjectHistoryWorkspace({
  repositories,
  selectedRepository,
  detail,
  isLoading,
  error,
  language,
  onOpenProject,
  onRefresh
}) {
  const isChinese = language === "zh-CN";
  const copy = {
    heading: isChinese ? "项目详情" : "Project details",
    subheading: isChinese
      ? "登录后的仓库历史会出现在这里。"
      : "Signed-in repository history appears here.",
    noProjects: isChinese ? "还没有保存过历史扫描。" : "No saved review history yet.",
    recentScore: isChinese ? "最近评分" : "Latest score",
    topRisks: isChinese ? "主要风险" : "Top risks",
    aiSummary: isChinese ? "AI 总结" : "AI summary",
    issueBacklog: isChinese ? "Issue 待办" : "Issue backlog",
    historyRuns: isChinese ? "历史扫描" : "History runs",
    trend: isChinese ? "趋势变化" : "Trend",
    open: isChinese ? "打开" : "Open",
    refresh: isChinese ? "刷新" : "Refresh",
    noRisks: isChinese ? "最近一次扫描没有重点风险。" : "The latest run has no priority risks.",
    noAi: isChinese ? "最近一次扫描没有 AI 总结。" : "No AI summary was saved for the latest run.",
    noIssues: isChinese ? "暂无需要创建的 Issue。" : "No immediate issue suggestions.",
    noRuns: isChinese ? "还没有历史扫描。" : "No historical runs yet.",
    newFindings: isChinese ? "新增" : "New",
    existingFindings: isChinese ? "持续" : "Existing",
    resolvedFindings: isChinese ? "已解决" : "Resolved",
    generated: isChinese ? "扫描时间" : "Scanned"
  };
  const latestRun = detail?.latestRun;
  const topRisks = (detail?.findings ?? []).filter((finding) =>
    importantSeverity.has((finding.severity || "info").toLowerCase())
  );
  const issueBacklog = (detail?.findings ?? []).filter(
    (finding) => (finding.severity || "info").toLowerCase() !== "info"
  );

  return (
    <section className="project-workspace" id="project-detail">
      <div className="project-workspace-head">
        <div>
          <p className="project-eyebrow">{copy.heading}</p>
          <h2>{selectedRepository?.repo_name || copy.subheading}</h2>
        </div>
        <button className="action-button" type="button" onClick={onRefresh} disabled={isLoading}>
          <RefreshCw size={16} className={isLoading ? "animate-spin" : ""} aria-hidden="true" />
          {copy.refresh}
        </button>
      </div>

      {error ? <p className="project-error">{error}</p> : null}

      <div className="project-layout">
        <aside className="project-list" aria-label={copy.heading}>
          {repositories.length ? (
            repositories.map((repository) => (
              <button
                key={repository.id}
                className={`project-list-item ${
                  selectedRepository?.id === repository.id ? "active" : ""
                }`}
                type="button"
                onClick={() => onOpenProject(repository)}
              >
                <strong>{repository.repo_name}</strong>
                <span>{repository.repo_url}</span>
              </button>
            ))
          ) : (
            <p className="project-empty">{copy.noProjects}</p>
          )}
        </aside>

        <div className="project-detail-panel">
          {!selectedRepository ? (
            <p className="project-empty">{copy.subheading}</p>
          ) : isLoading && !detail ? (
            <div className="project-loading">
              <RotateCcw size={18} className="animate-spin" aria-hidden="true" />
              <span>{isChinese ? "正在加载项目详情..." : "Loading project details..."}</span>
            </div>
          ) : (
            <>
              <div className="project-summary-grid">
                <MetricTile label={copy.recentScore} value={latestRun?.health_score ?? "--"} />
                <MetricTile label={copy.newFindings} value={latestRun?.new_findings_count ?? 0} />
                <MetricTile label={copy.existingFindings} value={latestRun?.existing_findings_count ?? 0} />
                <MetricTile label={copy.resolvedFindings} value={latestRun?.resolved_findings_count ?? 0} />
              </div>

              <div className="project-two-column">
                <DetailCard
                  title={copy.trend}
                  icon={<TrendingUp size={18} aria-hidden="true" />}
                >
                  <ScoreTrend runs={detail?.runs ?? []} emptyText={copy.noRuns} />
                </DetailCard>

                <DetailCard
                  title={copy.aiSummary}
                  icon={<CheckCircle2 size={18} aria-hidden="true" />}
                >
                  {detail?.aiReview?.summary ? (
                    <MarkdownSummary text={detail.aiReview.summary} />
                  ) : (
                    <p className="project-muted">{copy.noAi}</p>
                  )}
                </DetailCard>
              </div>

              <DetailCard
                title={copy.topRisks}
                icon={<AlertTriangle size={18} aria-hidden="true" />}
              >
                {topRisks.length ? (
                  <div className="project-risk-list">
                    {topRisks.slice(0, 5).map((finding) => (
                      <HistoryFindingCard key={finding.fingerprint} finding={finding} />
                    ))}
                  </div>
                ) : (
                  <p className="project-muted">{copy.noRisks}</p>
                )}
              </DetailCard>

              <div className="project-two-column">
                <DetailCard
                  title={copy.issueBacklog}
                  icon={<FileText size={18} aria-hidden="true" />}
                >
                  {issueBacklog.length ? (
                    <ul className="project-issue-list">
                      {issueBacklog.slice(0, 6).map((finding) => (
                        <li key={finding.fingerprint}>
                          <strong>{finding.title}</strong>
                          <span>{finding.recommendation}</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="project-muted">{copy.noIssues}</p>
                  )}
                </DetailCard>

                <DetailCard
                  title={copy.historyRuns}
                  icon={<GitBranch size={18} aria-hidden="true" />}
                >
                  {detail?.runs?.length ? (
                    <ol className="project-run-list">
                      {detail.runs.map((run) => (
                        <li key={run.id}>
                          <div>
                            <strong>{copy.generated}: {formatDate(run.created_at)}</strong>
                            <span>{run.branch || "main"} {run.commit_sha ? `· ${run.commit_sha.slice(0, 7)}` : ""}</span>
                          </div>
                          <Badge tone={scoreTone(run.health_score)}>{run.health_score ?? "--"}</Badge>
                        </li>
                      ))}
                    </ol>
                  ) : (
                    <p className="project-muted">{copy.noRuns}</p>
                  )}
                </DetailCard>
              </div>
            </>
          )}
        </div>
      </div>
    </section>
  );
}

function MetricTile({ label, value }) {
  return (
    <div className="project-metric-tile">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function DetailCard({ title, icon, children }) {
  return (
    <article className="project-detail-card">
      <header>
        {icon}
        <h3>{title}</h3>
      </header>
      {children}
    </article>
  );
}

function ScoreTrend({ runs, emptyText }) {
  if (!runs.length) {
    return <p className="project-muted">{emptyText}</p>;
  }
  const orderedRuns = [...runs].reverse();
  return (
    <div className="score-trend" role="list">
      {orderedRuns.map((run) => {
        const score = typeof run.health_score === "number" ? run.health_score : 0;
        return (
          <div className="score-trend-item" key={run.id} role="listitem">
            <span className="score-bar" style={{ height: `${Math.max(8, score)}%` }} />
            <strong>{score}</strong>
            <small>{formatShortDate(run.created_at)}</small>
          </div>
        );
      })}
    </div>
  );
}

function HistoryFindingCard({ finding }) {
  const severity = (finding.severity || "info").toLowerCase();
  return (
    <article className="history-finding-card">
      <div>
        <h4>{finding.title}</h4>
        <p>{finding.recommendation}</p>
        {(finding.evidence_paths_json ?? []).length ? (
          <small>{finding.evidence_paths_json.slice(0, 3).join(", ")}</small>
        ) : null}
      </div>
      <Badge tone={severity}>{severity}</Badge>
    </article>
  );
}

function scoreTone(score) {
  if (score >= 85) return "success";
  if (score >= 70) return "warning";
  return "error";
}

const severityStyles = {
  critical: "border-red-500 bg-red-50 text-red-950",
  high: "border-red-400 bg-red-50 text-red-950",
  medium: "border-amber-400 bg-amber-50 text-amber-950",
  low: "border-sky-400 bg-sky-50 text-sky-950",
  info: "border-emerald-400 bg-emerald-50 text-emerald-950"
};

const badgeStyles = {
  critical: "bg-red-100 text-red-800 ring-red-200",
  high: "bg-red-100 text-red-800 ring-red-200",
  medium: "bg-amber-100 text-amber-800 ring-amber-200",
  low: "bg-sky-100 text-sky-800 ring-sky-200",
  info: "bg-emerald-100 text-emerald-800 ring-emerald-200",
  neutral: "bg-stone-100 text-stone-700 ring-stone-200",
  success: "bg-emerald-100 text-emerald-800 ring-emerald-200",
  warning: "bg-amber-100 text-amber-800 ring-amber-200",
  error: "bg-red-100 text-red-800 ring-red-200"
};

const sectionToneStyles = {
  priority: "border-l-red-400 bg-red-50/50",
  insight: "border-l-emerald-400 bg-emerald-50/50",
  neutral: "border-l-stone-300 bg-stone-50/70",
  process: "border-l-slate-300 bg-slate-50"
};

const importantSeverity = new Set(["critical", "high", "medium"]);

const ReportView = React.forwardRef(function ReportView(
  { report, markdown, language, onCopy, onDownload, onClose },
  ref
) {
  const copy = reportCopy[language] ?? reportCopy.en;

  if (!report) {
    return (
      <section ref={ref} className="rounded-lg border border-slate-200 bg-white lg:col-span-2">
        <ReportToolbar copy={copy} onCopy={onCopy} onDownload={onDownload} onClose={onClose} />
        <pre className="max-h-[620px] overflow-auto whitespace-pre-wrap break-words bg-slate-50 p-4 text-sm leading-relaxed">
          {markdown}
        </pre>
      </section>
    );
  }

  const findings = report.findings ?? [];
  const priorityFindings = findings.filter((finding) =>
    importantSeverity.has((finding.severity || "info").toLowerCase())
  );
  const aiReview = report.ai_review;
  const aiStatusTone =
    aiReview?.status === "generated" ? "success" : aiReview ? "error" : "neutral";

  return (
    <section ref={ref} className="overflow-hidden rounded-lg border border-slate-200 bg-white lg:col-span-2">
      <ReportToolbar copy={copy} onCopy={onCopy} onDownload={onDownload} onClose={onClose} />

      <div className="space-y-4 bg-[#f7f8fa] p-4 md:p-5">
        <div className="rounded-lg border border-slate-200 bg-white p-5">
          <div className="grid gap-4 md:grid-cols-[1fr_auto] md:items-start">
            <div>
              <p className="mb-2 text-xs font-bold uppercase tracking-[0.16em] text-muted">
                {copy.repositoryReview}
              </p>
              <h2 className="text-2xl font-bold leading-tight tracking-normal text-ink md:text-3xl">
                {report.repo_name}
              </h2>
              <p className="mt-2 text-sm text-muted">
                {copy.generated} {formatDate(report.generated_at)}
              </p>
            </div>
            <div className="flex flex-wrap gap-2 md:justify-end">
              <Badge tone={priorityFindings.length ? "error" : "success"}>
                {priorityFindings.length
                  ? `${priorityFindings.length} ${copy.priority}`
                  : copy.noPriorityRisks}
              </Badge>
              <Badge tone={aiStatusTone}>AI {aiReview?.status ?? copy.aiNotSelected}</Badge>
            </div>
          </div>
        </div>

        <ReportSection
          title={copy.executiveSummary}
          tone="insight"
          icon={<CheckCircle2 size={18} aria-hidden="true" />}
        >
          <ul className="report-list">
            {(report.overview ?? []).map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </ReportSection>

        <ReportSection title={copy.metrics} tone="neutral">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {Object.entries(copy.metricLabels).map(([key, label]) => (
              <div key={key} className="metric-card">
                <span>{label}</span>
                <strong>{report.metrics?.[key] ?? 0}</strong>
              </div>
            ))}
          </div>
          {report.metrics?.languages ? (
            <div className="mt-3 flex flex-wrap gap-2">
              {Object.entries(report.metrics.languages).map(([name, count]) => (
                <Badge key={name} tone="neutral">
                  {name}: {count}
                </Badge>
              ))}
            </div>
          ) : null}
        </ReportSection>

        <ReportSection title={copy.frameworkSignals} tone="insight">
          {Object.keys(report.framework_signals ?? {}).length ? (
            <div className="grid gap-3 md:grid-cols-2">
              {Object.entries(report.framework_signals).map(([label, evidence]) => (
                <div key={label} className="rounded-md border border-emerald-100 bg-white p-3">
                  <strong className="block text-sm text-emerald-900">{label}</strong>
                  <p className="mt-1 text-sm leading-relaxed text-slate-600">
                    {(evidence ?? []).slice(0, 4).join(", ")}
                  </p>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted">{copy.noFrameworkSignals}</p>
          )}
        </ReportSection>

        {aiReview ? (
          <ReportSection
            title={copy.aiReview}
            tone={aiReview.status === "generated" ? "insight" : "priority"}
            icon={
              aiReview.status === "generated" ? (
                <CheckCircle2 size={18} aria-hidden="true" />
              ) : (
                <AlertTriangle size={18} aria-hidden="true" />
              )
            }
          >
            <div className="mb-3 flex flex-wrap gap-2">
              <Badge tone="neutral">
                {copy.provider}: {aiReview.provider}
              </Badge>
              <Badge tone="neutral">
                {copy.model}: {aiReview.model}
              </Badge>
              <Badge tone={aiReview.status === "generated" ? "success" : "error"}>
                {aiReview.status}
              </Badge>
            </div>
            {aiReview.status === "generated" ? (
              <MarkdownSummary text={aiReview.summary} />
            ) : (
              <p className="rounded-md border border-red-100 bg-white p-3 text-sm leading-relaxed text-red-800">
                {copy.aiReviewError}: {aiReview.error}
              </p>
            )}
          </ReportSection>
        ) : null}

        <ReportSection
          title={copy.findings}
          tone={priorityFindings.length ? "priority" : "insight"}
          icon={
            priorityFindings.length ? (
              <AlertTriangle size={18} aria-hidden="true" />
            ) : (
              <CheckCircle2 size={18} aria-hidden="true" />
            )
          }
        >
          <div className="space-y-3">
            {findings.map((finding, index) => (
              <FindingCard
                key={`${finding.title}-${index}`}
                finding={finding}
                index={index}
                copy={copy}
              />
            ))}
          </div>
        </ReportSection>

        <ReportSection
          title={copy.agentTrace}
          tone="process"
          icon={<Activity size={18} aria-hidden="true" />}
        >
          <AgentTraceTimeline trace={report.agent_trace ?? []} copy={copy} />
        </ReportSection>
      </div>
    </section>
  );
});

function RunProgress({ phases, activeIndex, elapsedSeconds, language }) {
  const progress = phases.length > 1 ? (activeIndex / (phases.length - 1)) * 100 : 100;
  const activePhase = phases[activeIndex] ?? phases[0];
  const isChinese = language === "zh-CN";

  return (
    <div className="run-progress" aria-live="polite">
      {activePhase ? (
        <div className="run-progress-head">
          <span className="run-status-dot" aria-hidden="true" />
          <div className="run-progress-current">
            <strong>{activePhase.label}</strong>
            <small>{activePhase.detail}</small>
          </div>
          <span className="run-progress-time">
            {isChinese ? `已运行 ${elapsedSeconds} 秒` : `${elapsedSeconds}s elapsed`}
          </span>
        </div>
      ) : null}
      <div className="run-progress-bar" aria-hidden="true">
        <span style={{ width: `${progress}%` }} />
      </div>
      <ol className="run-progress-steps">
        {phases.map((phase, index) => {
          const Icon = phase.icon;
          const state = index < activeIndex ? "done" : index === activeIndex ? "active" : "pending";
          return (
            <li key={phase.key} className={`run-progress-step ${state}`}>
              <span className="run-progress-icon">
                {state === "done" ? (
                  <CheckCircle2 size={18} aria-hidden="true" />
                ) : state === "active" ? (
                  <RotateCcw size={17} className="animate-spin" aria-hidden="true" />
                ) : (
                  <Icon size={17} aria-hidden="true" />
                )}
              </span>
              <span className="run-progress-text">
                <strong>{phase.label}</strong>
                <small>{phase.detail}</small>
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function AgentTraceTimeline({ trace, copy }) {
  if (!trace.length) {
    return <p className="text-sm text-muted">{copy.noTrace}</p>;
  }

  return (
    <ol className="trace-timeline">
      {trace.map((step, index) => (
        <li key={`${step.tool}-${index}`} className="trace-step">
          <div className="trace-marker">
            <span>{index + 1}</span>
          </div>
          <div className="trace-card">
            <div className="trace-card-header">
              <Badge tone="neutral">
                {copy.step} {index + 1}
              </Badge>
              <strong>{step.tool}</strong>
            </div>
            <p className="trace-thought">{step.thought}</p>
            <p className="trace-observation">{step.observation}</p>
            {step.tool_input ? (
              <pre className="trace-input">{JSON.stringify(step.tool_input, null, 2)}</pre>
            ) : null}
          </div>
        </li>
      ))}
    </ol>
  );
}

function ReportToolbar({ copy, onCopy, onDownload, onClose }) {
  return (
    <div className="grid gap-4 border-b border-slate-200 bg-white p-4 sm:grid-cols-[1fr_auto] sm:items-center">
      <h2 className="text-base font-bold tracking-normal">{copy.generatedReport}</h2>
      <div className="grid grid-cols-3 gap-2">
        <button className="action-button" type="button" onClick={onCopy}>
          <Clipboard size={17} />
          {copy.copy}
        </button>
        <button className="action-button" type="button" onClick={onDownload}>
          <Download size={17} />
          {copy.download}
        </button>
        <button className="action-button text-red-700" type="button" onClick={onClose}>
          <X size={17} />
          {copy.close}
        </button>
      </div>
    </div>
  );
}

function ReportSection({ title, tone = "neutral", icon, children }) {
  return (
    <section className={`report-section ${sectionToneStyles[tone] ?? sectionToneStyles.neutral}`}>
      <div className="mb-3 flex items-center gap-2">
        {icon ? <span className="text-current">{icon}</span> : null}
        <h3 className="text-lg font-bold tracking-normal text-ink">{title}</h3>
      </div>
      {children}
    </section>
  );
}

function FindingCard({ finding, index, copy }) {
  const severity = (finding.severity || "info").toLowerCase();
  const tone = severityStyles[severity] ?? severityStyles.info;

  return (
    <article className={`rounded-lg border-l-4 p-4 ${tone}`}>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h4 className="text-base font-bold tracking-normal">
            {index + 1}. {finding.title}
          </h4>
          <p className="mt-1 text-sm opacity-80">{finding.category}</p>
        </div>
        <Badge tone={severity}>{copy.severity[severity] ?? severity}</Badge>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-md bg-white/75 p-3">
          <strong className="mb-2 block text-sm">{copy.evidence}</strong>
          <ul className="report-list text-sm">
            {(finding.evidence ?? []).map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          {(finding.evidence_paths ?? []).length ? (
            <div className="mt-3">
              <strong className="mb-2 block text-sm">{copy.evidencePaths}</strong>
              <ul className="report-list text-sm">
                {finding.evidence_paths.map((path) => (
                  <li key={path}>
                    <code>{path}</code>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
        <div className="rounded-md bg-white/75 p-3">
          <strong className="mb-2 block text-sm">{copy.recommendation}</strong>
          <p className="text-sm leading-relaxed">{finding.recommendation}</p>
        </div>
      </div>
    </article>
  );
}

function Badge({ tone = "neutral", children }) {
  return (
    <span
      className={`inline-flex min-h-7 items-center rounded-full px-2.5 py-1 text-xs font-bold ring-1 ${
        badgeStyles[tone] ?? badgeStyles.neutral
      }`}
    >
      {children}
    </span>
  );
}

function MarkdownSummary({ text }) {
  const lines = (text || "").split("\n");
  const blocks = [];
  let list = [];

  const flushList = () => {
    if (!list.length) return;
    blocks.push({ type: "list", items: list });
    list = [];
  };

  lines.forEach((line) => {
    const trimmed = line.trim();
    if (!trimmed) {
      flushList();
      return;
    }
    const normalizedHeading = normalizeReviewHeading(trimmed);
    if (normalizedHeading) {
      flushList();
      blocks.push({ type: "heading", text: normalizedHeading });
      return;
    }
    if (trimmed.startsWith("### ")) {
      flushList();
      blocks.push({ type: "heading", text: trimmed.slice(4) });
      return;
    }
    if (trimmed.startsWith("## ")) {
      flushList();
      blocks.push({ type: "heading", text: trimmed.slice(3) });
      return;
    }
    if (trimmed === "-" || trimmed === "*") {
      return;
    }
    if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
      const listItem = trimmed.slice(2).trim();
      if (listItem) {
        list.push(listItem);
      }
      return;
    }
    flushList();
    blocks.push({ type: "paragraph", text: trimmed });
  });
  flushList();

  return (
    <div className="markdown-summary">
      {blocks.map((block, index) => {
        if (block.type === "heading") {
          return <h4 key={index}>{renderInlineMarkdown(block.text)}</h4>;
        }
        if (block.type === "list") {
          return (
            <ul key={index}>
              {block.items.map((item, itemIndex) => (
                <li key={`${item}-${itemIndex}`}>{renderInlineMarkdown(item)}</li>
              ))}
            </ul>
          );
        }
        return <p key={index}>{renderInlineMarkdown(block.text)}</p>;
      })}
    </div>
  );
}

function normalizeReviewHeading(trimmed) {
  if (/^(?:#{1,6}\s*)?简历亮点\s*[:：]?\s*$/.test(trimmed)) {
    return "项目亮点";
  }
  if (/^(?:#{1,6}\s*)?Resume Pitch\s*[:：]?\s*$/i.test(trimmed)) {
    return "Project Highlights";
  }
  return "";
}

function renderInlineMarkdown(text) {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g).filter(Boolean);
  return parts.map((part, index) => {
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={index}>{part.slice(1, -1)}</code>;
    }
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    return <React.Fragment key={index}>{part}</React.Fragment>;
  });
}

function formatDate(value) {
  if (!value) return "just now";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

createRoot(document.getElementById("root")).render(<App />);
