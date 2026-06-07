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
  FileSearch,
  FileText,
  ListChecks,
  RotateCcw,
  Search,
  Sparkles,
  X
} from "lucide-react";
import "./styles.css";

const DEFAULT_TARGET = "";

const MODEL_OPTIONS = [
  {
    value: "openrouter:auto",
    label: "OpenRouter Auto",
    provider: "openrouter",
    model: "openrouter/auto"
  },
  {
    value: "openai:gpt-5-mini",
    label: "GPT-5 mini",
    provider: "openai",
    model: "gpt-5-mini"
  },
  {
    value: "openai:gpt-5",
    label: "GPT-5",
    provider: "openai",
    model: "gpt-5"
  },
  {
    value: "ollama:llama3.2",
    label: "Llama 3.2",
    provider: "ollama",
    model: "llama3.2"
  },
  {
    value: "none",
    label: "Rules only",
    provider: "none",
    model: ""
  }
];

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
    noTrace: "No agent trace was recorded for this run.",
    step: "Step",
    provider: "Provider",
    model: "Model",
    status: "Status",
    evidence: "Evidence",
    recommendation: "Recommendation",
    issueBacklog: "GitHub Issue Backlog",
    noIssues: "No immediate issue suggestions.",
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
    noTrace: "本次运行没有记录 Agent 执行轨迹。",
    step: "步骤",
    provider: "提供方",
    model: "模型",
    status: "状态",
    evidence: "证据",
    recommendation: "建议",
    issueBacklog: "GitHub Issue 待办",
    noIssues: "暂无需要立即创建的 Issue 建议。",
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

const progressCopy = {
  en: [
    {
      key: "scan",
      label: "Scan repository",
      detail: "Map files, languages, manifests, and CI signals.",
      icon: Search
    },
    {
      key: "inspect",
      label: "Inspect key files",
      detail: "Read README, dependency files, CI, and docs.",
      icon: FileSearch
    },
    {
      key: "analyze",
      label: "Run rule checks",
      detail: "Generate deterministic findings and evidence.",
      icon: ListChecks
    },
    {
      key: "ai",
      label: "Synthesize AI review",
      detail: "Ask the selected model for structured review sections.",
      icon: Sparkles
    },
    {
      key: "render",
      label: "Render report",
      detail: "Build Markdown, JSON, issue suggestions, and trace.",
      icon: FileText
    }
  ],
  "zh-CN": [
    {
      key: "scan",
      label: "扫描仓库",
      detail: "识别文件、语言、依赖清单和 CI 信号。",
      icon: Search
    },
    {
      key: "inspect",
      label: "检查关键文件",
      detail: "读取 README、依赖文件、CI 和文档。",
      icon: FileSearch
    },
    {
      key: "analyze",
      label: "运行规则检查",
      detail: "生成确定性发现、证据和建议。",
      icon: ListChecks
    },
    {
      key: "ai",
      label: "生成 AI 评审",
      detail: "请求所选模型返回结构化评审内容。",
      icon: Sparkles
    },
    {
      key: "render",
      label: "渲染报告",
      detail: "生成 Markdown、JSON、Issue 建议和轨迹。",
      icon: FileText
    }
  ]
};

function buildDemoReport(language) {
  const isChinese = language === "zh-CN";
  return {
    repo_name: "GitHub-Repo-Review-Agent",
    generated_at: "2026-05-29T00:00:00+00:00",
    overview: isChinese
      ? [
          "检测到主要源码语言：Python (13), JavaScript (4)。",
          "发现依赖清单：pyproject.toml, frontend/package.json。",
          "通过 9 个测试文件检测到测试覆盖面。",
          "检测到 CI 配置：.github/workflows/ci.yml。",
          "框架和工具信号：FastAPI, React, Docker, MCP, OpenAI Function Calling。"
        ]
      : [
          "Primary source languages detected: Python (13), JavaScript (4).",
          "Dependency manifests found: pyproject.toml, frontend/package.json.",
          "Test coverage surface detected through 9 test file(s).",
          "CI configuration detected: .github/workflows/ci.yml.",
          "Framework and tooling signals: FastAPI, React, Docker, MCP, OpenAI Function Calling."
        ],
    metrics: {
      files_scanned: 52,
      files_skipped: 0,
      source_files: 17,
      test_files: 9,
      dependency_files: 3,
      ci_files: 1,
      languages: { Python: 13, JavaScript: 4 }
    },
    framework_signals: {
      FastAPI: ["src/repo_review_agent/web.py"],
      React: ["frontend/src/main.jsx"],
      Docker: ["Dockerfile", "docker-compose.prod.yml"],
      MCP: ["src/repo_review_agent/mcp_server.py"],
      "Function Calling": ["src/repo_review_agent/function_agent.py"]
    },
    ai_review: {
      provider: "openrouter",
      model: "openrouter/auto",
      status: "generated",
      summary: isChinese
        ? "## AI 架构总结\n这个项目已经从静态分析脚本扩展为一个完整的仓库评审 Agent。前端负责输入和报告展示，FastAPI 后端负责任务编排，自定义 Agent 按工具链执行扫描、文件检查、规则分析和 AI 总结。\n\n## 主要风险\n- 公开部署时需要限制请求频率和目标 URL，避免被滥用。\n- AI Provider key 必须只保存在后端环境变量中。\n\n## 项目亮点\n- 项目同时覆盖前端、后端、Docker 部署和 CI 配置，具备完整工具链雏形。\n- Agent 执行轨迹、结构化 JSON 和 Markdown 报告让评审过程更透明。\n- 支持多模型 Provider 和中英文报告，适合扩展成可演示的开发者工具。\n\n## 推荐下一步\n- 添加线上 Demo 链接和 Web UI 截图。\n- 在 CI 中持续验证 Docker build 和前端构建。"
        : "## AI Architecture Summary\nThis project has evolved from a static analysis script into a full repository review agent. The frontend collects review inputs and renders structured reports, while the FastAPI backend orchestrates scanning, file inspection, rule-based analysis, and AI synthesis.\n\n## Top Risks\n- Public deployments need rate limits and repository URL restrictions to reduce abuse.\n- AI provider keys must stay on the backend as environment variables.\n\n## Project Highlights\n- The project covers frontend, backend, Docker deployment, and CI configuration, giving it a complete developer-tool shape.\n- Agent traces, structured JSON, and Markdown output make the review process easier to inspect.\n- Multi-provider AI support and bilingual reports make the product more flexible for demos and real use.\n\n## Recommended Next Steps\n- Add a hosted demo link and Web UI screenshots.\n- Keep Docker build and frontend build checks in CI."
    },
    agent_trace: [
      {
        thought: isChinese
          ? "在做评审判断前，我需要先获得仓库的结构化地图。"
          : "I need a structured map of the repository before making review decisions.",
        tool: "scan_repository",
        tool_input: { path: "/demo/GitHub-Repo-Review-Agent" },
        observation: isChinese
          ? "扫描了 52 个文件，发现 17 个源码文件、9 个测试文件和 1 个 CI 文件。"
          : "Scanned 52 files, found 17 source files, 9 test files, and 1 CI file."
      },
      {
        thought: isChinese
          ? "我应该检查关键项目文件，然后运行确定性风险分析。"
          : "I should inspect important project files before deterministic risk analysis.",
        tool: "inspect_file",
        tool_input: { path: "README.md", max_chars: 4000 },
        observation: isChinese
          ? "已检查 README.md、pyproject.toml、Dockerfile 和 CI workflow。"
          : "Inspected README.md, pyproject.toml, Dockerfile, and the CI workflow."
      },
      {
        thought: isChinese
          ? "结构化发现已经准备好，可以请求模型生成总结评审。"
          : "The structured findings are ready, so I can ask the selected model to synthesize the review.",
        tool: "generate_ai_review",
        tool_input: { provider: "openrouter", model: "openrouter/auto" },
        observation: isChinese
          ? "已使用 OpenRouter 生成 AI Review。"
          : "Generated AI review with OpenRouter."
      }
    ],
    findings: [
      {
        title: isChinese ? "补充线上 Demo 截图和部署链接" : "Add hosted demo screenshots and deployment link",
        severity: "low",
        category: isChinese ? "展示" : "portfolio",
        evidence: isChinese
          ? ["项目已经具备 Web UI 和部署配置，但 README 中还没有真实截图。"]
          : ["The project includes a Web UI and deployment config, but the README does not yet show real screenshots."],
        recommendation: isChinese
          ? "部署后补充 Web UI 截图、示例报告截图和线上地址。"
          : "After deployment, add Web UI screenshots, report screenshots, and the live demo URL."
      },
      {
        title: isChinese ? "生产环境需要启用公开访问保护" : "Enable public access controls in production",
        severity: "medium",
        category: isChinese ? "安全" : "security",
        evidence: isChinese
          ? ["公开部署会接受用户输入的 GitHub URL，并调用后端分析流程。"]
          : ["A public deployment accepts user-provided GitHub URLs and runs backend analysis."],
        recommendation: isChinese
          ? "设置 REPO_REVIEW_ALLOW_LOCAL_TARGETS=false，并启用请求频率限制。"
          : "Set REPO_REVIEW_ALLOW_LOCAL_TARGETS=false and enable rate limiting."
      }
    ]
  };
}

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

          <div className="prompt-bar">
            <input
              className="repo-input"
              name="target"
              value={form.target}
              onChange={updateField}
              placeholder="put the repo you want to know"
              aria-label="GitHub repository URL"
            />
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

          {isRunning ? <RunProgress phases={runPhases} activeIndex={progressStep} /> : null}

          <div className="home-actions">
            <button className="demo-button" type="button" onClick={loadDemoReport}>
              <FileText size={17} aria-hidden="true" />
              Demo
            </button>
          </div>

          <p className="home-status" aria-live="polite">
            {status}
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

function RunProgress({ phases, activeIndex }) {
  const progress = phases.length > 1 ? (activeIndex / (phases.length - 1)) * 100 : 100;

  return (
    <div className="run-progress" aria-live="polite">
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

function renderStaticMarkdown(report, language) {
  const copy = reportCopy[language] ?? reportCopy.en;
  const lines = [
    `# ${copy.repositoryReview}: ${report.repo_name}`,
    "",
    `${copy.generated}: \`${report.generated_at}\``,
    "",
    `## ${copy.executiveSummary}`,
    "",
    ...(report.overview ?? []).map((item) => `- ${item}`),
    "",
    `## ${copy.metrics}`,
    "",
    ...Object.entries(copy.metricLabels).map(
      ([key, label]) => `- ${label}: \`${report.metrics?.[key] ?? 0}\``
    ),
    `- Languages: \`${Object.entries(report.metrics?.languages ?? {})
      .map(([name, count]) => `${name}: ${count}`)
      .join(", ")}\``,
    "",
    `## ${copy.frameworkSignals}`,
    ""
  ];

  Object.entries(report.framework_signals ?? {}).forEach(([label, evidence]) => {
    lines.push(`- **${label}**: ${(evidence ?? []).slice(0, 4).join(", ")}`);
  });

  if (report.ai_review) {
    lines.push(
      "",
      `## ${copy.aiReview}`,
      "",
      `- ${copy.provider}: \`${report.ai_review.provider}\``,
      `- ${copy.model}: \`${report.ai_review.model}\``,
      `- ${copy.status}: \`${report.ai_review.status}\``,
      "",
      report.ai_review.summary,
      ""
    );
  }

  if (report.agent_trace?.length) {
    lines.push("", `## ${copy.agentTrace}`, "");
    report.agent_trace.forEach((step, index) => {
      lines.push(
        `### ${copy.step} ${index + 1}: \`${step.tool}\``,
        "",
        `- Thought: ${step.thought}`,
        `- Input: \`${JSON.stringify(step.tool_input)}\``,
        `- Observation: ${step.observation}`,
        ""
      );
    });
  }

  lines.push("", `## ${copy.findings}`, "");
  (report.findings ?? []).forEach((finding, index) => {
    lines.push(
      `### ${index + 1}. ${finding.title}`,
      "",
      `- Severity: \`${finding.severity}\``,
      `- Category: \`${finding.category}\``,
      `- ${copy.evidence}:`
    );
    (finding.evidence ?? []).forEach((item) => lines.push(`  - ${item}`));
    lines.push(`- ${copy.recommendation}:`, `  - ${finding.recommendation}`, "");
  });

  lines.push("", `## ${copy.issueBacklog}`, "");
  const actionableFindings = (report.findings ?? []).filter((finding) => finding.severity !== "info");
  if (actionableFindings.length) {
    actionableFindings.forEach((finding) => {
      lines.push(`- [${finding.severity.toUpperCase()}] ${finding.title} - ${finding.recommendation}`);
    });
  } else {
    lines.push(`- ${copy.noIssues}`);
  }

  lines.push("");
  return lines.join("\n");
}

createRoot(document.getElementById("root")).render(<App />);
