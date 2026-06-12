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
  RotateCcw,
  X
} from "lucide-react";
import { DEFAULT_TARGET, MODEL_OPTIONS, progressCopy } from "./config";
import { buildDemoReport } from "./demoReport";
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

  const runReview = async (event) => {
    event.preventDefault();
    setIsRunning(true);
    setProgressStep(0);
    setElapsedSeconds(0);
    setStatus(isChinese ? "评审已开始，正在连接后端..." : "Review started. Connecting to backend...");
    setMarkdown("");
    setReport(null);

    const payload = {
      ...form,
      ai_model: form.ai_model.trim() || null
    };

    try {
      const response = await fetch("/review", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
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
      setStatus("Review complete.");
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
