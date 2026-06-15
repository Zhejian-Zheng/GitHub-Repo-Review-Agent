from __future__ import annotations

import json

from .i18n import normalize_report_language


def build_prompt_tuning_guidance(language: str | None = None) -> str:
    """Return compact prompt-tuning guidance shared by AI review entry points."""
    language = normalize_report_language(language)
    if language == "zh-CN":
        return "\n".join(
            [
                "- 以确定性扫描和 findings 作为事实来源；不要补充输入中不存在的文件、框架或风险。",
                "- 优先引用 evidence_paths 中的真实路径，并把严重程度转换成实际影响。",
                "- 如果 findings 很少或没有高风险，也要说明剩余风险和下一步加固方向。",
                "- 项目亮点必须来自扫描证据，例如测试、CI、Docker、框架信号或清晰的模块边界。",
                "- 输出只能是 JSON 对象；保留固定 key，数组内写自然语言句子，不写 Markdown。",
            ]
        )

    return "\n".join(
        [
            "- Treat deterministic scan data and findings as the source of truth; do not add files, frameworks, or risks absent from the input.",
            "- Prefer real paths from evidence_paths, and translate severity into practical engineering impact.",
            "- If findings are few or low severity, explain residual risk and concrete hardening steps instead of inventing problems.",
            "- Project highlights must be backed by scan evidence such as tests, CI, Docker, framework signals, or clear module boundaries.",
            "- Return only the JSON object; keep the fixed keys and write natural-language strings inside the arrays, not Markdown.",
        ]
    )


def build_few_shot_examples(language: str | None = None) -> str:
    """Return evidence-bound examples that tune the review style and JSON shape."""
    language = normalize_report_language(language)
    examples = _ZH_FEW_SHOT_EXAMPLES if language == "zh-CN" else _EN_FEW_SHOT_EXAMPLES
    return json.dumps(examples, indent=2, ensure_ascii=False)


_EN_FEW_SHOT_EXAMPLES = [
    {
        "input_pattern": "healthy-python-service with pytest, CI, Docker, and no high-severity findings",
        "good_response": {
            "architecture_summary": [
                "healthy-python-service looks like a compact Python service with its runtime code under src/, dependency metadata in pyproject.toml, and validation wired through tests/test_app.py and .github/workflows/ci.yml.",
                "The scan evidence points to a repository that already has the core portfolio signals in place: source code, tests, CI, and container packaging."
            ],
            "risks": [
                "No high-severity findings were detected, but Dockerfile remains important operational evidence to keep reviewing as runtime assumptions change."
            ],
            "project_highlights": [
                "The project demonstrates test and delivery discipline because pyproject.toml, tests/test_app.py, and .github/workflows/ci.yml are all present in the scan."
            ],
            "next_steps": [
                "Keep the report evidence-bound by expanding tests around any new service behavior before adding more AI narrative."
            ],
        },
    },
    {
        "input_pattern": "risky-js-app with floating dependencies, broad workflow permissions, missing tests, and an unpinned Docker base image",
        "good_response": {
            "architecture_summary": [
                "risky-js-app appears to be a JavaScript application with dependency metadata in package.json, a Docker runtime in Dockerfile, and CI configuration in .github/workflows/ci.yml.",
                "The repository has deployable shape, but the evidence shows the delivery path needs stronger reproducibility and permission boundaries."
            ],
            "risks": [
                "package.json uses floating or broad dependency versions, which makes installs less reproducible and can introduce unexpected behavior across environments.",
                ".github/workflows/ci.yml grants broad write permissions, increasing the impact of a compromised workflow or dependency step.",
                "Dockerfile uses an unpinned base image, so rebuilds can silently change the runtime."
            ],
            "project_highlights": [
                "The presence of package.json, Dockerfile, and .github/workflows/ci.yml gives the project enough structure for automated review and future hardening."
            ],
            "next_steps": [
                "Pin dependency ranges and commit a lockfile, narrow workflow permissions to least privilege, and pin the Docker base image before treating the pipeline as production-ready."
            ],
        },
    },
]

_ZH_FEW_SHOT_EXAMPLES = [
    {
        "input_pattern": "healthy-python-service：包含 pytest、CI、Docker，且没有高严重程度 findings",
        "good_response": {
            "architecture_summary": [
                "healthy-python-service 看起来是一个紧凑的 Python 服务，运行代码位于 src/，依赖元数据位于 pyproject.toml，并通过 tests/test_app.py 和 .github/workflows/ci.yml 建立验证路径。",
                "扫描证据显示，这个仓库已经具备作品集项目常见的核心信号：源码、测试、CI 和容器化入口。"
            ],
            "risks": [
                "当前没有检测到高严重程度问题，但 Dockerfile 仍然是需要持续审查的运行时证据，尤其是在服务依赖和部署假设变化时。"
            ],
            "project_highlights": [
                "pyproject.toml、tests/test_app.py 和 .github/workflows/ci.yml 同时存在，说明项目已经展示了测试和交付纪律。"
            ],
            "next_steps": [
                "在新增服务行为前先扩展对应测试，并继续让 AI 综述只引用扫描证据中真实存在的路径和风险。"
            ],
        },
    },
    {
        "input_pattern": "risky-js-app：存在浮动依赖、宽泛 workflow 权限、缺少测试和未固定 Docker 基础镜像",
        "good_response": {
            "architecture_summary": [
                "risky-js-app 看起来是一个 JavaScript 应用，依赖元数据位于 package.json，Docker 运行时入口位于 Dockerfile，CI 配置位于 .github/workflows/ci.yml。",
                "仓库已经有可交付的基础形态，但证据显示交付路径还需要加强可复现性和权限边界。"
            ],
            "risks": [
                "package.json 使用浮动或过宽的依赖版本，会降低安装可复现性，并可能让不同环境出现意外行为。",
                ".github/workflows/ci.yml 授予了宽泛的写权限，会放大 workflow 或依赖步骤被攻破后的影响。",
                "Dockerfile 使用未固定版本的基础镜像，后续 rebuild 可能在没有代码变化的情况下改变运行时。"
            ],
            "project_highlights": [
                "package.json、Dockerfile 和 .github/workflows/ci.yml 的存在让项目具备自动化审查和后续加固的结构基础。"
            ],
            "next_steps": [
                "先固定依赖范围并提交 lockfile，再把 workflow 权限收窄到最小权限，同时固定 Docker 基础镜像版本。"
            ],
        },
    },
]
