import React from "react";
import { Activity, AlertTriangle, CheckCircle2, Clipboard, Download, RotateCcw, X } from "lucide-react";
import { MarkdownSummary } from "./MarkdownSummary";
import { reportCopy } from "../reportCopy";
import { Badge, formatDate, importantSeverity } from "./shared";
const severityStyles = {
  critical: "border-red-500 bg-red-50 text-red-950",
  high: "border-red-400 bg-red-50 text-red-950",
  medium: "border-amber-400 bg-amber-50 text-amber-950",
  low: "border-sky-400 bg-sky-50 text-sky-950",
  info: "border-emerald-400 bg-emerald-50 text-emerald-950"
};

const sectionToneStyles = {
  priority: "border-l-red-400 bg-red-50/50",
  insight: "border-l-emerald-400 bg-emerald-50/50",
  neutral: "border-l-stone-300 bg-stone-50/70",
  process: "border-l-slate-300 bg-slate-50"
};

export const ReportView = React.forwardRef(function ReportView(
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

export function RunProgress({ phases, activeIndex, elapsedSeconds, language }) {
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

