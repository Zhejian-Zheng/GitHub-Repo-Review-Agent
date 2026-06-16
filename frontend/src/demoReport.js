export function buildDemoReport(language) {
  const isChinese = language === "zh-CN";
  return {
    repo_name: "GitHub-Repo-Review-Agent",
    generated_at: "2026-05-29T00:00:00+00:00",
    overview: isChinese
      ? [
          "检测到主要源码语言：Python (13), JavaScript (4)。",
          "发现依赖清单：pyproject.toml, frontend/package.json。",
          "通过 20+ 个测试文件检测到测试覆盖面。",
          "检测到 CI 配置：.github/workflows/ci.yml。",
          "框架和工具信号：FastAPI, React, Docker, Supabase, Render, GitHub Pages, MCP。"
        ]
      : [
          "Primary source languages detected: Python (13), JavaScript (4).",
          "Dependency manifests found: pyproject.toml, frontend/package.json.",
          "Test coverage surface detected through 20+ test file(s).",
          "CI configuration detected: .github/workflows/ci.yml.",
          "Framework and tooling signals: FastAPI, React, Docker, Supabase, Render, GitHub Pages, MCP."
        ],
    metrics: {
      files_scanned: 52,
      files_skipped: 0,
      source_files: 17,
      test_files: 20,
      dependency_files: 3,
      ci_files: 1,
      languages: { Python: 13, JavaScript: 4 }
    },
    framework_signals: {
      FastAPI: ["src/repo_review_agent/web.py"],
      React: ["frontend/src/main.jsx"],
      Docker: ["Dockerfile", "docker-compose.prod.yml", "deploy/render.Dockerfile"],
      Render: ["render.yaml"],
      "GitHub Pages": [".github/workflows/pages.yml"],
      Supabase: ["supabase/schema.sql", "supabase/verify_history_schema.sql"],
      MCP: ["src/repo_review_agent/mcp_server.py"],
      "Function Calling": ["src/repo_review_agent/function_agent.py"]
    },
    ai_review: {
      provider: "openrouter",
      model: "openrouter/auto",
      status: "generated",
      summary: isChinese
        ? "## AI 架构总结\n这个项目已经从静态分析脚本扩展为一个可部署的仓库评审平台。GitHub Pages 承载静态前端，Render 运行 FastAPI 后端，Supabase 负责登录和历史记录。\n\n## 主要风险\n- 公开部署仍然依赖正确的环境变量：CORS origin、Supabase service role key、请求频率限制和 GitHub URL 限制都必须在 Render 中保持开启。\n- AI Provider key 必须只保存在后端环境变量中。\n\n## 项目亮点\n- 项目同时覆盖前端、后端、数据库 schema、认证、Docker、Render、GitHub Pages 和 CI 配置，已经具备完整线上 demo 路径。\n- Agent 执行轨迹、结构化 JSON 和 Markdown 输出让评审过程更透明。\n- Supabase 历史记录、项目详情页和双语报告让产品形态更接近真实开发者工具。\n\n## 推荐下一步\n- 补充 Web UI 截图和端到端 demo 截图。\n- 在公开 demo 稳定后，把最终线上地址和截图放进 README。"
        : "## AI Architecture Summary\nThis project has evolved from a static analysis script into a deployable repository review platform. GitHub Pages serves the static frontend, Render runs the FastAPI backend, and Supabase handles auth plus review history.\n\n## Top Risks\n- Public deployments still depend on correct environment variables: CORS origins, the Supabase service role key, rate limits, and GitHub URL restrictions must stay enabled on Render.\n- AI provider keys must stay on the backend as environment variables.\n\n## Project Highlights\n- The project covers frontend, backend, database schema, auth, Docker, Render, GitHub Pages, and CI configuration, giving it a complete hosted-demo path.\n- Agent traces, structured JSON, and Markdown output make the review process easier to inspect.\n- Supabase history, the project detail view, and bilingual reports make the product feel closer to a real developer tool.\n\n## Recommended Next Steps\n- Add Web UI screenshots and end-to-end demo screenshots.\n- After the public demo is stable, add the final live URL and screenshots to the README."
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
        title: isChinese ? "补充线上 Demo 截图" : "Add hosted demo screenshots",
        severity: "low",
        category: isChinese ? "展示" : "portfolio",
        evidence: isChinese
          ? ["README 已经包含 Live Demo 入口和部署说明，但还没有真实 Web UI 截图。"]
          : ["The README includes the live demo entry point and deployment guide, but it does not yet show real Web UI screenshots."],
        evidence_paths: ["README.md", "docs/hosted-demo.md"],
        recommendation: isChinese
          ? "端到端测试稳定后，补充首页、报告结果和项目详情页截图。"
          : "After the end-to-end demo is stable, add screenshots of the home page, report output, and project detail view."
      },
      {
        title: isChinese ? "公开部署保护已配置" : "Public deployment controls are configured",
        severity: "info",
        category: isChinese ? "安全" : "security",
        evidence: isChinese
          ? ["FastAPI 后端支持 CORS 白名单、请求频率限制、登录要求和 GitHub URL 限制。"]
          : ["The FastAPI backend supports CORS allowlists, request rate limits, login requirements, and GitHub URL restrictions."],
        evidence_paths: ["src/repo_review_agent/web.py", "render.yaml", "docs/hosted-demo.md"],
        recommendation: isChinese
          ? "在 Render 中保持 REPO_REVIEW_ALLOW_LOCAL_TARGETS=false、REPO_REVIEW_REQUIRE_AUTH=true，并只把 service role key 放在后端环境变量中。"
          : "Keep REPO_REVIEW_ALLOW_LOCAL_TARGETS=false and REPO_REVIEW_REQUIRE_AUTH=true on Render, and keep the service role key backend-only."
      }
    ]
  };
}
