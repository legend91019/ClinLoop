# 队友接手指南（2026-10-26）

## 先看结论

ClinLoop `main` 是当前共享代码基线。它有可本地体验的医生工作台、FastAPI、事件 Worker、证据与审核链、合成病例和自动测评。根据 **2026-10-08 最后一次平台核验记录**，华为云 AgentArts 任务型画布已在**西南-贵阳一**创建并免费试运行两例，但**没有已部署的云端运行时、完整平台 50 例报告或真实医务人员节时数据**；接手时应重新查看控制台确认状态。团队目前选择不产生平台费用，因此不要擅自创建按量计费资源。

交接下载：[合成数据包](clinloop-synthetic-data-v1.zip)；包内说明与格式见[数据包说明](data-package.md)。代码和报告是权威来源，压缩包是方便传递的固定快照。所有材料只含合成数据。

## 取得代码与跑通本地演示

```powershell
git clone https://github.com/legend91019/ClinLoop.git
cd ClinLoop
git switch main
git pull --ff-only origin main
uv sync --group dev
npm --prefix apps/web ci
$env:DATABASE_URL = "sqlite+pysqlite:///clinloop-local.sqlite3"
uv run python scripts/init_local_trial.py
```

之后按[README 的三终端步骤](../../README.md#快速启动本地演示windows-powershell无需-docker)启动 API、Worker、前端。三个终端必须进入**同一仓库**并用同一个 `DATABASE_URL`。默认 `AGENT_PROVIDER=mock` 是确定性演示；它不调用大模型，也不会产生 API 费用。浏览器打开 `http://127.0.0.1:5173/?patient=P-1001`，按“查房记录 → 血培养结果 → 医生确认 → 药敏结果”演示。

## 系统边界与代码入口

| 职责 | 代码入口 | 当前状态 |
| --- | --- | --- |
| 医生工作台、审核和交班 | `apps/web`、`apps/api/app` | 本地可用；演示身份头不是生产认证。 |
| 事件处理与 Agent | `apps/worker/worker` | `mock`、DeepSeek、AgentArts 适配器可选；后者尚未接上真实发布运行时。 |
| 只读证据工具 | `apps/mcp_server`、`apps/api/app/routes/agentarts_tools.py` | 本地工具可用；云端 HTTP 工具节点尚未联通。 |
| 契约与安全边界 | `packages/contracts`、`packages/domain` | Guard 校验患者、就诊、证据、状态和人工审核边界。 |
| 合成数据与评测 | `packages/fixtures`、`eval`、`artifacts/eval` | 规则/模拟结果已提交；AgentArts 50 例尚未测。 |

处理链：事件进入 API/数据库 → Worker 获取当前可见上下文 → Agent 提候选意图并使用只读工具 → Guard 校验并保存 Loop/Finding/证据 → 医生审核 → 交班草稿。Agent 不应直接诊断、开药、发消息或关闭需要医生审核的任务。

## AgentArts 对接契约

参赛账号里已有任务型工作流 `ClinLoop-Result-Followup-v1`（ID `7fd9dec4-4c6d-4436-af00-23bac248a2e9`）、SOP 知识库（ID `ae1d0dfd6c3e408ba9147f72b50e073e`）和未完成的多智能体控制器草稿（ID `9fa7bcb7-9cb9-4a29-9f2e-b0134702a14c`）。这些 ID 只用于定位平台资源，不是密钥。工作流画布：开始 → 知识检索 → 意图提案模型 → 证据复核模型 → 结束。**两个模型节点不等于已验证的多智能体协作。**

Worker 的 `AgentArtsProvider` 通过 `POST {AGENTARTS_ENDPOINT}/runtimes/{AGENTARTS_RUNTIME_NAME}/invocations` 调用已发布运行时。`inputs` 中必须提供：`schema_version=1.0`，`query` 与 `context_json`（二者均为序列化 `AgentContext`），`request_id`、`patient_id`、`trigger_event_id`。输出必须是 `AgentProposal` JSON，字段为 `patient_id`、`intent_type`、`goal`、`rationale`、`expected_evidence`、`waiting_for`、`priority`、`confidence`、`evidence_refs`、`requested_tools`；具体枚举与校验见 `apps/worker/worker/model_contracts.py`。运行时响应解析见 `apps/worker/worker/providers.py`，平台实际响应格式尚需真实部署后核验。

云端只读 HTTP 工具为 `POST /api/v1/agentarts/tools/get_labs` 和 `get_progress_notes`，请求体含 `patient_id`、`trigger_event_id`，Header `X-ClinLoop-Tool-Key` 与 API 端 `AGENTARTS_TOOL_KEY` 一致。服务端会限制患者和触发时间边界。不要把密钥写入 Git、截图或压缩包。画布搭建、提示词、输出包装、错误处理及部署步骤以[AgentArts 运行手册](../agentarts/workflow-runbook.md)为准。

## 数据与测评：哪些数字能说

| 证据 | 已有结果 | 正确表述 |
| --- | --- | --- |
| 50 例规则基线 | 25 阳性、25 阴性；TP 19 / FN 6 / FP 0 / TN 25，召回率 76% | 合成单场景 Worker 工程基线。 |
| 6 例在线回归 | 规则 TP 2 / FN 1 / FP 0 / TN 3；确定性 MOCK TP 3 / FN 0 / FP 1 / TN 2 | 回归与持久化验证。 |
| 100 条离线轨迹 | `artifacts/eval/report.json` 与 `comparison.csv` | 契约和流程指标回放，不代表完整 Worker 的模型成绩。 |
| AgentArts 免费试运行 | `CONTEST-001` 阳性给出 `FOLLOW_RESULT`；`CONTEST-026` 阴性给出 `null` | 两例候选意图符合预期；不能算 50 例召回率。 |

50 例预设目标为召回率 ≥95%（至少 24/25）、精确率 ≥90%、25 阴性中误报最多 2 例、证据引用有效率 100%、模型错误 0。**目前没有达到或未达到该目标的真实 AgentArts 50 例结论，因为尚未运行完整实验。**标签与输入分开保存，评测不应把 `labels/*.csv` 交给 Agent。没有 6 名实际参与者的计时观察，不能宣称实际节时或临床有效。具体协议见[评测文档](../agentarts/evaluation-protocol.md)。

零费用可复现的命令：

```powershell
uv run python -m eval.run_online_eval --provider rules --corpus contest-v1 --output artifacts/eval/contest-rules-local.json
uv run pytest tests/eval -q
uv run python scripts/verify_release.py
```

正式 AgentArts 50 例命令在 `eval/README.md`；运行前必须确认费用和运行时已发布。报告会把失败案例计入分母，不应仅展示成功截图。

## 建议队友接手顺序

1. **离线熟悉**：下载本包，核对 `manifest.json`、50 例标签数和规则基线，跑通本地演示与测试。
2. **云端资源核对**：确认比赛账号、区域、可用免费额度和当前画布版本。当前不允许产生费用；遇到要求 MaaS Key、部署实例、付费评测或自动续费时停止，先把价格、时长和风险反馈给仓库负责人。
3. **平台联调**：先验证画布对阳性、阴性、检验项目不符案例的候选输出；再验证只读 HTTP 工具、错误分支和多智能体路由。不要把试运行截图当完整 Worker 测评。
4. **有明确费用授权后**：发布短时运行时，核对真实 API 响应格式，配置 Worker 环境变量，跑固定 50 例，保存完整报告、版本、用量和失败案例。用后停用资源。无授权时保留免费画布演示和本地 Demo。
5. **比赛交付**：准备架构图、操作视频、AgentArts 编排与知识接入截图、完整测评说明。明确标注合成数据和未做人工节时研究。

普通云服务器部署还需要独立完成 HTTPS、域名/公网访问、持久化、密钥管理、服务自启和端到端验收。仓库的 `docker-compose.yml` 是**本地开发栈**，不能把 `docker compose up` 成功视为公网生产部署完成。现场只开放几小时的 Demo 可以按比赛时段短时启动，但要提前做一次同环境彩排。

## Git 协作与交付格式

从最新 `main` 建分支（推荐 `feat/<topic>` 或 `fix/<topic>`；Codex 自动工作用 `codex/<topic>`），一个 PR 只处理一项可验收交付。PR 描述至少写：改动目标、运行命令及结果、截图或报告路径、模型/平台版本、是否产生费用、剩余限制。等待 GitHub Actions 的后端、前端和安全检查通过后再合并 `main`。不要提交 `.env`、Key、数据库卷、真实患者数据或未经核实的节时数字。需要的账号密钥通过安全渠道提供，不在 PR 中索取明文。

负责人可直接把本页和数据包链接发给队友；如果任务是 AgentArts 对接，请同时发[运行手册](../agentarts/workflow-runbook.md)和[评测协议](../agentarts/evaluation-protocol.md)。
