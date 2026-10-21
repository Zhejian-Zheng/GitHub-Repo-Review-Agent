import React, { useState } from "react";
import { AlertTriangle, CheckCircle2, FileText, GitBranch, RefreshCw, RotateCcw, TrendingUp } from "lucide-react";
import { MarkdownSummary } from "./MarkdownSummary";
import { Badge, formatDate, importantSeverity } from "./shared";
export function ProjectHistoryWorkspace({
  repositories,
  selectedRepository,
  detail,
  isLoading,
  error,
  language,
  onOpenProject,
  onFeedback,
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
                <MetricTile label={copy.recentScore} value={detail?.effective_health_score ?? latestRun?.health_score ?? "--"} />
                <MetricTile label={copy.newFindings} value={latestRun?.new_findings_count ?? 0} />
                <MetricTile label={copy.existingFindings} value={latestRun?.existing_findings_count ?? 0} />
                <MetricTile label={copy.resolvedFindings} value={latestRun?.resolved_findings_count ?? 0} />
              </div>

              {detail?.unverified_findings?.length ? (
                <DetailCard title={`${isChinese ? "未复核" : "Not reverified"} (${detail.unverified_findings.length})`} icon={<AlertTriangle size={18} aria-hidden="true" />}>
                  <p className="project-muted">{isChinese
                    ? "以下旧问题未完成复核，不能视为已解决。当前评分仅反映本次检出的发现。"
                    : "These earlier findings were not fully rechecked and are not confirmed fixed. The score reflects only current findings."}</p>
                  <ul>{detail.unverified_findings.map(finding => <li key={finding.fingerprint}>{finding.title}</li>)}</ul>
                </DetailCard>
              ) : null}
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
                      <HistoryFindingCard key={finding.fingerprint} finding={finding} onFeedback={onFeedback} language={language} />
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
            <small>{formatDate(run.created_at)}</small>
          </div>
        );
      })}
    </div>
  );
}

function HistoryFindingCard({ finding, onFeedback, language }) {
  const severity = (finding.severity || "info").toLowerCase();
  return (
    <article className="history-finding-card">
      <div>
        <h4>{finding.title}</h4>
        <p>{finding.recommendation}</p>
        {onFeedback ? <FindingFeedbackForm finding={finding} language={language} onSave={payload => onFeedback(finding, payload)} /> : null}
        {(finding.evidence_paths_json ?? []).length ? (
          <small>{finding.evidence_paths_json.slice(0, 3).join(", ")}</small>
        ) : null}
      </div>
      <Badge tone={severity}>{severity}</Badge>
    </article>
  );
}

function FindingFeedbackForm({ finding, onSave, language }) {
  const chinese = language === "zh-CN";
  const [decision, setDecision] = useState(finding.feedback?.status || "confirmed");
  const [reason, setReason] = useState(finding.feedback?.reason || "");
  const [expiry, setExpiry] = useState(finding.feedback?.expires_at?.slice(0, 10) || "");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const save = async event => {
    event.preventDefault(); setBusy(true); setMessage("");
    try {
      await onSave({ status: decision, reason, expires_at: expiry ? new Date(`${expiry}T23:59:59Z`).toISOString() : null });
      setMessage(chinese ? "已保存" : "Decision saved.");
    } catch (error) { setMessage(error.message); }
    finally { setBusy(false); }
  };
  return <form className="finding-feedback" onSubmit={save}>
    <label>{chinese ? "处理决定" : "Finding decision"}<select aria-label="Finding decision" value={decision} onChange={event => setDecision(event.target.value)}>
      <option value="confirmed">{chinese ? "确认问题" : "Confirmed"}</option>
      <option value="false_positive">{chinese ? "误报" : "False positive"}</option>
      <option value="ignored">{chinese ? "忽略" : "Ignored"}</option>
    </select></label>
    <label>{chinese ? "原因" : "Reason"}<input aria-label="Feedback reason" maxLength={2000} value={reason} onChange={event => setReason(event.target.value)} /></label>
    <label>{chinese ? "到期日期（可选）" : "Expiry (optional)"}<input aria-label="Feedback expiry" type="date" value={expiry} onChange={event => setExpiry(event.target.value)} /></label>
    <button type="submit" disabled={busy}>{chinese ? "保存决定" : "Save decision"}</button>
    <small role="status">{message}</small>
  </form>;
}

function scoreTone(score) {
  if (score >= 85) return "success";
  if (score >= 70) return "warning";
  return "error";
}

