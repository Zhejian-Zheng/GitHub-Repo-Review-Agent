# LangChain Agent 重构设计（已批准并实施）

## 目标与默认约束

用 LangChain 作为仓库审查 agent 的实际执行框架，替换手写工具循环与模型 HTTP 接入；按需要重写和删除重复代码。成功标准是现有 CLI、Web、MCP 和报告消费方能够使用新的执行内核，而非仅增加一个 LangChain 示例。

默认保留产品已有能力：本地目录及 GitHub 输入、无 API key 的静态审查、中英文、结构化报告、历史记录、登录、GitHub 集成与部署方式。允许更新内部接口和测试；旧公开参数用薄兼容层过渡。无需因迁移框架重写独立且有效的扫描规则或前端页面。

## 现状

- `agent.py` 使用手写计划器和工具循环。
- `function_agent.py` 独立实现 OpenAI Responses 工具协议、状态和循环。
- `chatgpt_agent.py` 包装后一条执行路径并修改 provider 标签。
- `llm.py` 自行处理多供应商 HTTP 请求，同时承担提示词和输出解析。
- CLI 和 Web 分别选择执行路径；MCP 使用自定义 agent。
- 现有测试大量 mock 旧 HTTP 和内部实现，需要迁移到框架模型与工具边界。

## 方案取舍

1. **推荐：统一 LangChain agent、模型适配和共享审查工具。** 模型驱动路径使用 `langchain.agents.create_agent`；离线路径使用 LangGraph 显式工作流及相同业务工具。保留无需模型的能力，消除重复执行内核。
2. 只将 HTTP 换成 LangChain 模型：改动较少，但保留两套手写循环，不满足全面框架迁移目标。
3. 所有审查都强制使用模型：实现路径较少，但破坏离线、演示和自动化审查能力，不推荐。

## 组件与数据流

### 共享工具与运行状态

抽取单一审查会话，拥有仓库根目录、扫描快照、已读取文件和基础报告。每次运行创建独立会话，禁止跨请求共享可变状态。将扫描、文件读取、分析和报告预览封装为具备参数 schema 的 LangChain tools。工具只读取目标仓库，不运行仓库内代码。

文件读取限制在解析后的仓库根目录下，包含符号链接越界检查、读取长度限制和参数验证。分析前确保扫描存在；最终输出前确保基础报告存在。报告不能仅由模型文本伪造。

### 执行内核

- 无模型：显式工作流执行扫描、重点文件读取、确定性分析及最终报告，保留步骤 trace。
- 有模型的 agent：先准备基础扫描和确定性报告，再由 `create_agent` 调用共享工具补充证据、生成结构化评审。固定准备阶段保证模型失败仍可返回可用基础报告。
- 直接分析：保留轻量业务入口；若启用 AI 总结，使用与 agent 相同的 LangChain 模型工厂和评审 schema。
- 设置有界模型调用和工具执行次数，限制上下文、工具输出和模型输出；预算耗尽不标记为成功。
- trace 记录实际工具、参数和观察结果，不制造模型推理内容。

### 模型与结构化输出

统一配置 OpenAI、OpenRouter、Anthropic 和 Ollama 的 LangChain 集成。保留现有环境变量以及模型、超时、输出长度和 Ollama 地址参数。供应商集成可通过 extras 安装，缺失依赖返回明确安装说明。

模型返回四个非空字符串列表：`architecture_summary`、`risks`、`project_highlights`、`next_steps`。采用 Pydantic 校验和有界输出修复；不支持工具调用的模型返回明确错误，不偷偷切换供应商。纯总结路径允许使用可验证的 JSON 输出兼容供应商差异。

保留现有证据约束、中英文提示及 few-shot，仓库内容始终视为不可信数据。模型异常统一转为 `AIProviderError`，根据 `fail_on_ai_error` 返回带错误状态的基础报告或抛出错误。超时与重试有界，错误不得包含 API key。

### 入口与兼容

CLI、Web 与 MCP 共享新的审查服务，减少配置和分支重复。旧 `--agent`、`--function-calling`、`--chatgpt-agent` 及 Web mode 值继续可用，但映射到新内核；历史类名最多保留薄适配层，移除旧循环和手写模型请求。

维持 `ReviewReport`、Markdown/JSON 格式与 AI 状态契约，新增框架标识不改变数据库结构。检查 UI 的模式说明，更新与实际执行一致的文案。登录、持久化、PR bot 和 GitHub 写入继续沿用原有权限边界。

## 依赖与交付

实施时验证 LangChain/LangGraph 与各模型集成的兼容版本，保留现有 Python 支持范围的前提下设定依赖上界；如必须提升 Python 要求，同步更新 CI、Docker、部署配置和 README。核心安装支持离线工作流，模型供应商按 extras 安装，完整安装入口包含全部已有供应商。

更新 README 的架构、安装及运行示例、环境变量说明和部署文档。删除已无调用方的旧协议工具与对应实现细节测试，保留并迁移业务行为测试。

## 验证与验收

1. 离线运行无需 key 或网络，现有 golden fixtures 的发现及评分保持一致。
2. 用 LangChain fake chat model 验证真实框架中的工具调用、参数错误、结构化结果、无最终输出及调用预算耗尽；不能仅 mock 掉整个 agent 后声称框架可用。
3. 验证失败降级、严格错误模式、路径越界、符号链接、读取上限、语言和多次运行状态隔离。
4. 验证各供应商配置映射，测试不调用付费 API。
5. 验证 CLI 兼容参数、Web 请求与报告结构、MCP、历史记录与 PR bot 回归。
6. 运行项目要求的测试、Ruff、覆盖率及受影响的前端构建；不通过降低覆盖率阈值掩盖迁移缺口。
7. 实际执行本地仓库审查并检查 Markdown/JSON 输出。没有凭据时，清楚区分离线框架验证与尚未执行的真实供应商联调。

## 官方接口依据

- https://reference.langchain.com/python/langchain/agents/factory/create_agent
- https://github.com/langchain-ai/docs/blob/main/src/oss/langchain/structured-output.mdx
- https://github.com/langchain-ai/docs/blob/main/src/oss/langgraph/workflows-agents.mdx

方案已获用户批准并完成实施；验证结果见同目录上级 plans/2026-09-20-langchain-rebuild.md。
