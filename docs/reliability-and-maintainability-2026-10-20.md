# 可信度、资源控制与维护成本改进（2026-10-20）

本次完成六项评审建议，并额外修复复查中发现的两处前端状态问题。未提交、未推送、未部署，也未修改线上数据库或调用付费模型。

## 1. 中文报告的反馈身份

- 新增 `ReviewReport.findings_canonical`；序列化报告只认 `findings` 集合，`ai_review.findings` 仅保留为模型原始证据，不再在每次展示时重新合并。
- 本地化前先固化指纹：翻译、脱敏、重复导出和历史恢复都保留原指纹，因此 `ignored` / `false_positive` 反馈在中文报告重载后仍然生效。
- 恢复逻辑兼容两种旧报告：只有 AI 发现的旧格式，以及同时含两份英文投影、但没有规范标记的旧格式。已经损坏并写入两个不同指纹的历史记录不会自动改写。
- 回归测试覆盖中英文、忽略/误报、连续三次恢复、PR JSON 重载、旧格式和空规范集合，见 [test_finding_identity.py](../tests/test_finding_identity.py)。
- 行为说明见 [finding-lifecycle.md](finding-lifecycle.md)。

## 2. AI 问答的并发与超时

- 新增独立的 [question_runtime.py](../src/repo_review_agent/question_runtime.py)：全局并发、单用户并发、每分钟准入次数和总执行超时，配额耗尽返回 429，超时返回 504。
- 模型问答在可终止的子进程中执行，容量在成功、模型失败、配额拒绝、超时和进程异常时由 `finally` 释放；服务关闭后拒绝新准入。
- 内存模式按实例限流；Supabase 模式通过 [20261020_question_capacity.sql](../supabase/migrations/20261020_question_capacity.sql) 的租约表与 RPC 在多进程间共享容量，租约到期自动回收。
- 离线 `provider: none` 不消耗模型容量或每日配额；模型问答与审查任务继续共享每日配额。
- 配置、部署顺序和进程范围见 [question-capacity.md](question-capacity.md)。

## 3. 从“规则命中”到“缺陷判断”的评测

- 新增六个可人工检查的语义样例：除零、带保护的除零反例、SQL 注入、参数化 SQL 反例、跨文件路径穿越，以及 README 中含提示注入的干净项目，见 [semantic/dataset.json](../tests/fixtures/semantic/dataset.json)。
- 评测支持带缺陷 ID、描述和精确行号范围的标签；`evidence_location_precision/recall` 只匹配真实引用与有界范围，重复发现、错误文件和伪造引用都会降低精度。
- 自动指标明确不冒充语义正确性：`semantic_precision/recall` 保持空值，直到独立人工判定；导出的候选保留标签、模型、试用次数、延迟和实际 token 用量。
- 原卫生数据集补齐了穷尽的可接受发现标签，CI 现在以 `--min-precision 1` 运行，precision 不再缺失。
- 文档给出离线门禁和可选的真实模型评测命令，见 [evaluation.md](evaluation.md#code-defect-benchmark-and-human-review)。

## 4. 后台任务与 Web 模块解耦

- 请求模型移入 [requests.py](../src/repo_review_agent/requests.py)，审查用例移入 [application.py](../src/repo_review_agent/application.py)，仓库获取移入 [targets.py](../src/repo_review_agent/targets.py)，调度与任务生命周期移入 [review_jobs.py](../src/repo_review_agent/review_jobs.py)。
- [job_runtime.py](../src/repo_review_agent/job_runtime.py) 只依赖应用层和请求模型，不再从 `web` 导入，也不会因后台进程导入而创建 FastAPI 应用或要求安装 HTTP 依赖。
- 子进程回归测试显式禁止导入 `fastapi`、`uvicorn`、`repo_review_agent.web` 和 `repo_review_agent.cli`，并验证核心依赖下仍能产出报告。
- `web.py` 保留原有公开名称的兼容导出，HTTP 与 CLI 行为未改变。

## 5. 前端拆分与异步状态

- `main.jsx` 从 1,836 行降到 289 行；认证、任务、历史分别进入 [useAuthSession.js](../frontend/src/hooks/useAuthSession.js)、[useReviewJob.js](../frontend/src/hooks/useReviewJob.js)、[useProjectHistory.js](../frontend/src/hooks/useProjectHistory.js)，展示组件按功能放入 `features/`。
- 增加会话代次：退出登录后，迟到的刷新、登录和历史详情响应不能恢复旧会话；项目详情、反馈刷新和任务轮询各自具备取消与当前性校验。
- 复查中额外发现并修复：
  - URL/OAuth 会话首次加载时，用户信息补全曾中断首次历史列表请求，导致列表为空且不再重试。
  - 过期且没有 refresh token 的会话曾因内部清理改变会话代次而停留在“已登录”界面。
- 前端测试：10 项 Vitest；13 项 Chrome Playwright，覆盖登录、任务恢复/取消、迟到响应、退出后重新登录、历史未复核显示、反馈并发保存、URL 会话补全和过期会话回登录页。

## 6. 可复现构建与兼容性

- 新增 `uv.lock`，锁定 101 个包，覆盖默认、Web、MCP、数据库测试、Langfuse 和各模型提供商依赖；构建后端 `setuptools` 固定为 `80.9.0`。
- CI 使用 `uv sync --locked --all-extras`，矩阵覆盖 Python 3.10（声明下限）和 3.12（生产解释器），前端、浏览器和 Docker 步骤只在 3.12 运行。
- 两个 Dockerfile 改用锁定安装，并把 `/app/.venv/bin` 放入 PATH；升级、验证和镜像边界见 [reproducible-builds.md](reproducible-builds.md)。
- 本地 `uv lock --check` 通过；在独立的 Python 3.10 环境完成锁定安装并跑通完整后端测试；锁定 Ruff 0.17.1 检查通过。

## 验证结果

- 后端：489 项测试，488 通过、1 项真实模型测试跳过；Python 3.14 本地环境和 Python 3.10 锁定环境均通过。
- 覆盖率：96%，高于 95% 门禁。
- PostgreSQL：在一次性本地 UTF8 集群运行 15 项集成测试，全部通过，包括问答并发、限流、租约过期、RLS 拒绝和原子历史。
- Ruff、`compileall`、离线卫生评测（precision 与 recall 均为 1）通过。
- 前端：10 项单元测试、13 项 Chrome 浏览器流程、生产构建通过。
- 未执行：真实付费模型评测、Docker 镜像构建（本机没有 Docker）、生产迁移/部署、真实 Supabase/OAuth 联调。

## 部署注意

部署新后端前，按顺序应用原子历史、`20261008_resolution_coverage.sql` 和 `20261020_question_capacity.sql`。问答容量在多副本间的一致性依赖最后一个迁移；未应用时准入会失败关闭，而不是绕过限制。
