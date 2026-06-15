from __future__ import annotations

import re
from dataclasses import replace

from .models import AIReview, Finding, ReviewReport

DEFAULT_REPORT_LANGUAGE = "en"
SUPPORTED_REPORT_LANGUAGES = {
    "en": "English",
    "zh-CN": "Simplified Chinese",
}

AI_SECTION_HEADINGS = {
    "en": [
        "## AI Architecture Summary",
        "## Top Risks",
        "## Project Highlights",
        "## Recommended Next Steps",
    ],
    "zh-CN": [
        "## AI 架构总结",
        "## 主要风险",
        "## 项目亮点",
        "## 推荐下一步",
    ],
}


def normalize_report_language(language: str | None) -> str:
    if not language:
        return DEFAULT_REPORT_LANGUAGE

    normalized = language.strip().lower().replace("_", "-")
    if normalized in {"en", "english"}:
        return "en"
    if normalized in {"zh", "zh-cn", "cn", "chinese", "simplified-chinese"}:
        return "zh-CN"
    return DEFAULT_REPORT_LANGUAGE


def language_display_name(language: str | None) -> str:
    return SUPPORTED_REPORT_LANGUAGES[normalize_report_language(language)]


def ai_section_headings(language: str | None) -> list[str]:
    return AI_SECTION_HEADINGS[normalize_report_language(language)]


def localize_report(report: ReviewReport, language: str | None) -> ReviewReport:
    language = normalize_report_language(language)
    if language == "en":
        return report

    return replace(
        report,
        overview=[_localize_overview_zh(item) for item in report.overview],
        findings=[_localize_finding_zh(finding) for finding in report.findings],
        ai_review=_localize_ai_review_zh(report.ai_review),
        agent_trace=[
            replace(
                step,
                thought=_localize_agent_thought_zh(step.thought),
                observation=_localize_agent_observation_zh(step.observation),
            )
            for step in report.agent_trace or []
        ]
        if report.agent_trace
        else report.agent_trace,
    )


def _localize_overview_zh(text: str) -> str:
    replacements = [
        (
            r"^Primary source languages detected: (.+)\.$",
            "检测到主要源码语言：{0}。",
        ),
        (
            r"^Dependency manifests found: (.+)\.$",
            "发现依赖清单：{0}。",
        ),
        (
            r"^Test coverage surface detected through (\d+) test file\(s\)\.$",
            "通过 {0} 个测试文件检测到测试覆盖面。",
        ),
        (
            r"^CI configuration detected: (.+)\.$",
            "检测到 CI 配置：{0}。",
        ),
        (
            r"^Framework and tooling signals: (.+)\.$",
            "框架和工具信号：{0}。",
        ),
    ]
    for pattern, template in replacements:
        match = re.match(pattern, text)
        if match:
            return template.format(*match.groups())

    exact = {
        "No application source files were detected in the scanned sample.": "扫描样本中未检测到应用源码文件。",
        "No dependency manifest was found.": "未发现依赖清单。",
        "No test files were detected.": "未检测到测试文件。",
        "No CI workflow files were detected.": "未检测到 CI 工作流文件。",
    }
    return exact.get(text, text)


def _localize_finding_zh(finding: Finding) -> Finding:
    return Finding(
        title=_FINDING_TITLE_ZH.get(finding.title, finding.title),
        severity=finding.severity,
        category=_CATEGORY_ZH.get(finding.category, finding.category),
        evidence=[_localize_evidence_zh(item) for item in finding.evidence],
        recommendation=_RECOMMENDATION_ZH.get(finding.recommendation, finding.recommendation),
        evidence_paths=finding.evidence_paths,
    )


def _localize_evidence_zh(text: str) -> str:
    match = re.match(r"^(\d+) source file\(s\) found, but no tests were detected\.$", text)
    if match:
        return f"发现 {match.group(1)} 个源码文件，但未检测到测试文件。"

    match = re.match(r"^Only (\d+) test file\(s\) were found for (\d+) source file\(s\)\.$", text)
    if match:
        return f"仅发现 {match.group(1)} 个测试文件，对应 {match.group(2)} 个源码文件。"

    match = re.match(r"^README\.md is missing (.+)\.$", text)
    if match:
        missing = (
            match.group(1)
            .replace("setup or usage instructions", "安装或使用说明")
            .replace("example output, demo, or screenshots", "示例输出、演示或截图")
        )
        return f"README.md 缺少 {missing}。"

    match = re.match(r"^CI files were found \((.+)\), but no common test command was detected\.$", text)
    if match:
        return f"已发现 CI 文件（{match.group(1)}），但未检测到常见测试命令。"

    match = re.match(r"^(.+) does not set a non-root USER before runtime\.$", text)
    if match:
        return f"{match.group(1)} 未在运行阶段前设置非 root USER。"

    match = re.match(r"^(\d+) file\(s\) were skipped because of limits or read errors\.$", text)
    if match:
        return f"有 {match.group(1)} 个文件因扫描限制或读取错误被跳过。"

    match = re.match(r"^(.+): secret-like value matched (.+)$", text)
    if match:
        return f"{match.group(1)}：匹配到疑似密钥模式 {match.group(2)}"

    match = re.match(r"^(.+): (.+) uses floating version (.+)$", text)
    if match:
        return f"{match.group(1)}：{match.group(2)} 使用浮动版本 {match.group(3)}"

    match = re.match(r"^(.+): (.+) is unconstrained$", text)
    if match:
        return f"{match.group(1)}：{match.group(2)} 未设置版本约束"

    match = re.match(r"^(.+): FROM (.+)$", text)
    if match:
        return f"{match.group(1)}：基础镜像 FROM {match.group(2)} 未固定版本"

    return _EVIDENCE_ZH.get(text, text)


def _localize_ai_review_zh(ai_review: AIReview | None) -> AIReview | None:
    if ai_review is None:
        return None
    return replace(ai_review, error=_AI_ERROR_ZH.get(ai_review.error, ai_review.error))


def _localize_agent_thought_zh(text: str) -> str:
    return _AGENT_THOUGHT_ZH.get(text, text)


def _localize_agent_observation_zh(text: str) -> str:
    match = re.match(
        r"^Scanned (\d+) file\(s\), found (\d+) source file\(s\), (\d+) test file\(s\), and (\d+) CI file\(s\)\.$",
        text,
    )
    if match:
        return (
            f"扫描了 {match.group(1)} 个文件，发现 {match.group(2)} 个源码文件、"
            f"{match.group(3)} 个测试文件和 {match.group(4)} 个 CI 文件。"
        )

    match = re.match(r"^Inspected (.+): (\d+) line\(s\)\. Preview: (.+)$", text)
    if match:
        return f"已检查 {match.group(1)}：{match.group(2)} 行。预览：{match.group(3)}"

    match = re.match(r"^Inspected (.+): file was empty or unreadable\.$", text)
    if match:
        return f"已检查 {match.group(1)}：文件为空或无法读取。"

    match = re.match(r"^Generated (\d+) finding\(s\) after inspecting (\d+) key file\(s\)\.$", text)
    if match:
        return f"检查 {match.group(2)} 个关键文件后生成 {match.group(1)} 条发现。"

    match = re.match(r"^Generated AI review with (.+)\.$", text)
    if match:
        return f"已使用 {match.group(1)} 生成 AI Review。"

    match = re.match(
        r"^AI review failed but the agent preserved the base report: (.+)$",
        text,
    )
    if match:
        error = _AI_ERROR_ZH.get(match.group(1), match.group(1))
        return f"AI Review 生成失败，但 Agent 已保留基础报告：{error}"

    match = re.match(r"^Rendered Markdown preview with (\d+) character\(s\)\.$", text)
    if match:
        return f"已渲染 Markdown 预览，共 {match.group(1)} 个字符。"

    return text


_FINDING_TITLE_ZH = {
    "Add a README with setup and usage instructions": "补充包含安装和使用说明的 README",
    "Add an explicit open-source license": "补充明确的开源许可证",
    "Add a .gitignore file": "添加 .gitignore 文件",
    "Add automated tests for the core behavior": "为核心行为添加自动化测试",
    "Add a CI workflow": "添加 CI 工作流",
    "Add a dependency manifest": "添加依赖清单",
    "Review skipped files": "检查被跳过的文件",
    "Remove possible hard-coded secrets": "移除可能硬编码的敏感密钥",
    "No major project hygiene gaps detected": "未检测到主要项目规范问题",
    "Expand README with setup and example output": "补充 README 的安装说明和示例输出",
    "Expand test coverage across source modules": "扩大源码模块的测试覆盖",
    "Run automated tests in CI": "在 CI 中运行自动化测试",
    "Build frontend assets in CI": "在 CI 中构建前端产物",
    "Commit a JavaScript package lockfile": "提交 JavaScript 包管理锁文件",
    "Harden Docker image with a non-root runtime user": "使用非 root 运行用户加固 Docker 镜像",
    "Pin broad or floating dependency versions": "固定宽泛或浮动的依赖版本",
    "Restrict GitHub Actions workflow permissions": "收紧 GitHub Actions 工作流权限",
    "Pin Docker base image versions": "固定 Docker 基础镜像版本",
}

_CATEGORY_ZH = {
    "documentation": "文档",
    "project hygiene": "项目规范",
    "testing": "测试",
    "delivery": "交付",
    "maintainability": "可维护性",
    "analysis coverage": "分析覆盖率",
    "security": "安全",
    "summary": "总结",
    "dependency hygiene": "依赖规范",
}

_EVIDENCE_ZH = {
    "README.md was not found.": "未发现 README.md。",
    "No LICENSE file was detected.": "未检测到 LICENSE 文件。",
    ".gitignore was not found.": "未发现 .gitignore。",
    "No workflow file was found under .github/workflows or other common CI locations.": "未在 .github/workflows 或其他常见 CI 位置发现工作流文件。",
    "No package manager manifest was detected.": "未检测到包管理器依赖清单。",
    "README, license, dependency metadata, tests, and CI signals were present in the scan.": "扫描中已发现 README、许可证、依赖元数据、测试和 CI 信号。",
    "package.json was found without package-lock.json, pnpm-lock.yaml, yarn.lock, or bun.lock.": "发现 package.json，但未发现 package-lock.json、pnpm-lock.yaml、yarn.lock 或 bun.lock。",
    "A JavaScript frontend package was detected, but CI does not appear to run a frontend build command.": "检测到 JavaScript 前端包，但 CI 中似乎没有运行前端构建命令。",
    "One or more GitHub Actions workflows grant write-level permissions.": "一个或多个 GitHub Actions 工作流授予了写级别权限。",
}

_RECOMMENDATION_ZH = {
    "Add a concise README that explains the project goal, setup steps, commands, and sample output.": "添加简洁的 README，说明项目目标、安装步骤、运行命令和示例输出。",
    "Add a LICENSE file so users know how they can use and adapt the code.": "添加 LICENSE 文件，让使用者明确如何使用和改造这份代码。",
    "Ignore virtual environments, caches, build outputs, local reports, and secrets.": "忽略虚拟环境、缓存、构建产物、本地报告和敏感配置。",
    "Add small tests around the scanner and analyzer so regressions are caught before release.": "围绕 scanner 和 analyzer 添加小型测试，提前发现回归问题。",
    "Run tests and basic import checks on pull requests using GitHub Actions.": "使用 GitHub Actions 在 Pull Request 中运行测试和基础导入检查。",
    "Add pyproject.toml, package.json, go.mod, or the equivalent manifest for the stack.": "根据技术栈添加 pyproject.toml、package.json、go.mod 或等价的依赖清单。",
    "Increase scan limits or inspect skipped files manually if they are relevant to the review.": "如果这些文件与评审相关，提升扫描限制或手动检查被跳过的文件。",
    "Move credentials into environment variables or a secret manager, then rotate exposed values.": "将凭证移入环境变量或密钥管理服务，并轮换已经暴露的值。",
    "Continue with deeper checks such as dependency vulnerability scanning and coverage thresholds.": "继续加入更深入的检查，例如依赖漏洞扫描和测试覆盖率阈值。",
    "Add installation steps, run commands, and a small report/demo screenshot so reviewers can understand the project quickly.": "添加安装步骤、运行命令和小型报告或演示截图，让评审者能快速理解项目。",
    "Add focused tests for the main source modules and track coverage thresholds in CI.": "为主要源码模块添加有针对性的测试，并在 CI 中跟踪覆盖率阈值。",
    "Add language-specific test commands to CI so regressions are caught before merge.": "在 CI 中添加对应语言的测试命令，在合并前捕获回归问题。",
    "Run npm run build, pnpm build, or the equivalent frontend build command in CI.": "在 CI 中运行 npm run build、pnpm build 或等价的前端构建命令。",
    "Commit the package manager lockfile so dependency resolution is reproducible in CI and deployments.": "提交包管理器锁文件，确保 CI 和部署环境中的依赖解析可复现。",
    "Create and switch to an application user in the final Docker stage to reduce container privilege risk.": "在最终 Docker 阶段创建并切换到应用用户，降低容器权限风险。",
    "Replace latest, wildcard, and unconstrained dependency versions with explicit compatible ranges or pinned versions so builds are reproducible.": "将 latest、通配符和无约束依赖版本替换为明确的兼容范围或固定版本，确保构建可复现。",
    "Set the narrowest required permissions for each workflow, default to read-only contents access, and grant write access only to jobs that need it.": "为每个工作流设置最小必要权限，默认仅授予只读 contents 访问，并只给确实需要的 job 写权限。",
    "Use explicit, maintained base image tags instead of latest or untagged images so container builds are reproducible.": "使用明确且仍维护的基础镜像标签，避免 latest 或未标记镜像，确保容器构建可复现。",
}

_AI_ERROR_ZH = {
    "OPENAI_API_KEY is not set.": "OPENAI_API_KEY 未设置。",
    "OpenAI response did not contain text output.": "OpenAI 响应中没有文本输出。",
    "Ollama response did not contain text output.": "Ollama 响应中没有文本输出。",
    "Model did not return a final text response.": "模型没有返回最终文本响应。",
}

_AGENT_THOUGHT_ZH = {
    "I need a structured map of the repository before making review decisions.": "在做评审判断前，我需要先获得仓库的结构化地图。",
    "I should inspect important project files before producing risk findings.": "在生成风险发现前，我应该先检查关键项目文件。",
    "I have enough repository context to run deterministic risk analysis.": "我已经有足够的仓库上下文，可以运行确定性风险分析。",
    "The structured findings are ready, so I can ask the selected model to synthesize the review.": "结构化发现已经准备好，可以请求所选模型生成总结评审。",
    "The review report is complete and should be rendered for the user.": "评审报告已经完成，可以渲染给用户。",
    "The model requested this tool through OpenAI function calling.": "模型通过 OpenAI function calling 请求了这个工具。",
}
