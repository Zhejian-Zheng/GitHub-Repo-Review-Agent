import { FileSearch, FileText, ListChecks, Search, Sparkles } from "lucide-react";

export const DEFAULT_TARGET = "";

export const MODEL_OPTIONS = [
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

export const progressCopy = {
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
