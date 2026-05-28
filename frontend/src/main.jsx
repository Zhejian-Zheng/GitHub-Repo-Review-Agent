import React, { useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  AlertTriangle,
  CheckCircle2,
  Clipboard,
  Download,
  FileText,
  GitBranch,
  Play,
  RotateCcw,
  X
} from "lucide-react";
import "./styles.css";

const DEFAULT_TARGET = "https://github.com/Zhejian-Zheng/GitHub-Repo-Review-Agent";

const reportCopy = {
  en: {
    generatedReport: "Generated Report",
    repositoryReview: "Repository Review",
    generated: "Generated",
    noPriorityRisks: "No priority risks",
    priority: "priority",
    aiNotSelected: "not selected",
    executiveSummary: "Executive Summary",
    metrics: "Metrics",
    frameworkSignals: "Framework Signals",
    noFrameworkSignals: "No framework signals were detected.",
    aiReview: "AI Review",
    aiReviewError: "AI review was not generated",
    findings: "Findings",
    agentTrace: "Agent Trace",
    step: "Step",
    provider: "Provider",
    model: "Model",
    evidence: "Evidence",
    recommendation: "Recommendation",
    copy: "Copy",
    download: "Download",
    close: "Close",
    metricLabels: {
      files_scanned: "Files scanned",
      files_skipped: "Files skipped",
      source_files: "Source files",
      test_files: "Test files",
      dependency_files: "Dependencies",
      ci_files: "CI files"
    },
    severity: {
      critical: "Critical",
      high: "High",
      medium: "Medium",
      low: "Low",
      info: "Info"
    }
  },
  "zh-CN": {
    generatedReport: "生成的报告",
    repositoryReview: "仓库评审",
    generated: "生成时间",
    noPriorityRisks: "暂无重点风险",
    priority: "重点风险",
    aiNotSelected: "未选择",
    executiveSummary: "执行摘要",
    metrics: "指标",
    frameworkSignals: "框架信号",
    noFrameworkSignals: "未检测到框架信号。",
    aiReview: "AI 评审",
    aiReviewError: "AI 评审未生成",
    findings: "发现",
    agentTrace: "Agent 执行轨迹",
    step: "步骤",
    provider: "提供方",
    model: "模型",
    evidence: "证据",
    recommendation: "建议",
    copy: "复制",
    download: "下载",
    close: "关闭",
    metricLabels: {
      files_scanned: "扫描文件数",
      files_skipped: "跳过文件数",
      source_files: "源码文件数",
      test_files: "测试文件数",
      dependency_files: "依赖清单数",
      ci_files: "CI 文件数"
    },
    severity: {
      critical: "严重",
      high: "高",
      medium: "中",
      low: "低",
      info: "信息"
    }
  }
};

function App() {
  const [form, setForm] = useState({
    target: DEFAULT_TARGET,
    mode: "agent",
    ai_provider: "none",
    ai_model: "",
    report_language: "en"
  });
  const [status, setStatus] = useState("Ready");
  const [isRunning, setIsRunning] = useState(false);
  const [markdown, setMarkdown] = useState("");
  const [report, setReport] = useState(null);
  const reportRef = useRef(null);

  const metrics = report?.metrics ?? {};
  const trace = report?.agent_trace ?? [];
  const findings = report?.findings ?? [];

  const summaryItems = useMemo(
    () => [
      ["Files", metrics.files_scanned ?? 0],
      ["Sources", metrics.source_files ?? 0],
      ["Tests", metrics.test_files ?? 0],
      ["Findings", findings.length]
    ],
    [metrics.files_scanned, metrics.source_files, metrics.test_files, findings.length]
  );

  const updateField = (event) => {
    const { name, value } = event.target;
    setForm((current) => ({ ...current, [name]: value }));
  };

  const runReview = async (event) => {
    event.preventDefault();
    setIsRunning(true);
    setStatus("Running review...");
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
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "Review failed");
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

  return (
    <main className="mx-auto grid max-w-6xl grid-cols-1 gap-5 px-4 py-6 text-ink lg:grid-cols-[390px_minmax(0,1fr)] lg:px-6">
      <section className="rounded-lg border border-slate-200 bg-white p-5">
        <div className="mb-5 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
            <GitBranch size={22} aria-hidden="true" />
          </div>
          <div>
            <h1 className="text-2xl font-bold leading-tight tracking-normal">Repo Review Agent</h1>
            <p className="text-sm text-muted">Generate a review report from a GitHub repository.</p>
          </div>
        </div>

        <form onSubmit={runReview} className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <label className="block sm:col-span-2">
            <span className="field-label">GitHub URL</span>
            <input
              className="field-input"
              name="target"
              value={form.target}
              onChange={updateField}
              placeholder="https://github.com/owner/repo"
            />
          </label>

          <label className="block">
            <span className="field-label">Mode</span>
            <select className="field-input" name="mode" value={form.mode} onChange={updateField}>
              <option value="agent">Custom Agent</option>
              <option value="direct">Direct Analysis</option>
              <option value="function-calling">OpenAI Function Calling</option>
            </select>
          </label>

          <label className="block">
            <span className="field-label">AI Provider</span>
            <select
              className="field-input"
              name="ai_provider"
              value={form.ai_provider}
              onChange={updateField}
            >
              <option value="none">None</option>
              <option value="ollama">Ollama</option>
              <option value="openai">OpenAI</option>
              <option value="openrouter">OpenRouter</option>
            </select>
          </label>

          <label className="block">
            <span className="field-label">Report Language</span>
            <select
              className="field-input"
              name="report_language"
              value={form.report_language}
              onChange={updateField}
            >
              <option value="en">English</option>
              <option value="zh-CN">简体中文</option>
            </select>
          </label>

          <label className="block">
            <span className="field-label">Model</span>
            <input
              className="field-input"
              name="ai_model"
              value={form.ai_model}
              onChange={updateField}
              placeholder="llama3.2, gpt-5-mini, or openrouter/auto"
            />
          </label>

          <button
            className="inline-flex min-h-10 items-center justify-center gap-2 rounded-md bg-blue-600 px-4 py-2 font-bold text-white transition hover:bg-blue-700 disabled:cursor-wait disabled:opacity-65 sm:col-span-2"
            type="submit"
            disabled={isRunning}
          >
            {isRunning ? <RotateCcw size={18} className="animate-spin" /> : <Play size={18} />}
            Generate Report
          </button>
        </form>

        <p className="mt-3 min-h-6 text-sm text-muted">{status}</p>
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-5">
        <div className="mb-4 flex items-center gap-2">
          <FileText size={18} className="text-blue-700" aria-hidden="true" />
          <h2 className="text-base font-bold tracking-normal">Run Summary</h2>
        </div>

        <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
          {summaryItems.map(([label, value]) => (
            <div key={label} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
              <span className="mb-2 block text-xs font-bold text-muted">{label}</span>
              <strong className="block text-2xl leading-none tracking-normal">{value}</strong>
            </div>
          ))}
        </div>

        <div className="min-h-80 rounded-lg border border-slate-200 bg-slate-50 p-4">
          {trace.length ? (
            <ol className="list-decimal space-y-3 pl-5 text-sm leading-relaxed">
              {trace.map((step, index) => (
                <li key={`${step.tool}-${index}`}>
                  <strong>{step.tool}</strong>
                  <br />
                  <span className="text-muted">{step.observation}</span>
                </li>
              ))}
            </ol>
          ) : (
            <p className="text-sm leading-relaxed text-muted">
              No review has been generated yet. The agent trace will appear here after a run.
            </p>
          )}
        </div>
      </section>

      {markdown ? (
        <ReportView
          ref={reportRef}
          report={report}
          markdown={markdown}
          language={form.report_language}
          onCopy={copyReport}
          onDownload={downloadReport}
          onClose={closeReport}
        />
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

        <details className="rounded-lg border border-slate-200 bg-white">
          <summary className="cursor-pointer px-4 py-3 text-sm font-bold text-slate-700">
            {copy.agentTrace}
          </summary>
          <ol className="space-y-3 border-t border-slate-200 bg-slate-50 p-4">
            {(report.agent_trace ?? []).map((step, index) => (
              <li key={`${step.tool}-${index}`} className="trace-item">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone="neutral">
                    {copy.step} {index + 1}
                  </Badge>
                  <strong>{step.tool}</strong>
                </div>
                <p>{step.thought}</p>
                <p>{step.observation}</p>
              </li>
            ))}
          </ol>
        </details>
      </div>
    </section>
  );
});

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
    if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
      list.push(trimmed.slice(2));
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
              {block.items.map((item) => (
                <li key={item}>{renderInlineMarkdown(item)}</li>
              ))}
            </ul>
          );
        }
        return <p key={index}>{renderInlineMarkdown(block.text)}</p>;
      })}
    </div>
  );
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
