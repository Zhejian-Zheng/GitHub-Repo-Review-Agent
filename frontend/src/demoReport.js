export function buildDemoReport(language) {
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
        evidence_paths: ["README.md", ".github/workflows/pages.yml"],
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
        evidence_paths: ["src/repo_review_agent/web.py"],
        recommendation: isChinese
          ? "设置 REPO_REVIEW_ALLOW_LOCAL_TARGETS=false，并启用请求频率限制。"
          : "Set REPO_REVIEW_ALLOW_LOCAL_TARGETS=false and enable rate limiting."
      }
    ]
  };
}
