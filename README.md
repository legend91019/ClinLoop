# ClinLoop MVP

事件驱动、可暂停和恢复的住院临床工作流连续性 Agent。

ClinLoop 持续追踪医生提出的 **Clinical Intent**，在医嘱（Plan）→ 执行（Order/Execution）→ 结果（Result）→ 医生响应（Response）→ 交接（Handoff）之间建立可审计的证据链，并把断裂点显式暴露为 **workflow gap** 交回医生审核。

> **工程验证，不构成临床有效性证明。** 全部数据为合成或脱敏数据。

## 1. 产品边界

ClinLoop **只做**：

- 追踪 Intent 与 Open Loop 的连续性，产出带证据绑定的 Finding。
- 暂停（suspend）/ 唤醒（resume）/ 重规划（re-plan）。
- 生成交接草稿并审计全部状态变化。

ClinLoop **不做**：

- 自动诊断、治疗推荐。
- 开立、修改或停止医嘱。
- 自动关闭高风险临床任务。
- 把模型推断直接写入正式病历。

Agent 只产生**候选状态变化**和证据；状态合法性、权限、审核和安全边界由 **Deterministic Guard** 判定，高风险转换必须经医生审核。

## 2. 架构

```text
React 医生工作台 (apps/web)
        │  REST
        ▼
FastAPI 业务 API (apps/api)  ──────►  PostgreSQL 16
        ▲                                     ▲
        │                                     │
   Redis Streams (事件总线)                     │
        │                                     │
        ▼                                     │
Python Worker + Workflow Agent (apps/worker) ──┤
        │  MCP (只读工具白名单)                  │
        ▼                                     │
Python MCP Server (apps/mcp_server) ───────────┘

packages/contracts  共享 Pydantic 契约（先于功能冻结）
packages/domain     状态机、Guard、领域规则
packages/fixtures   合成病例、事件、种子
eval/               轨迹生成、回放、baseline、指标
```

主轨迹：**Event Stream → API → Worker → MCP → Workflow Memory → Guard → Doctor Review → Web**。
Agent 循环：**OBSERVE → REASON → PLAN → ACT → VERIFY**。

## 3. 安全声明

- 只使用合成或脱敏数据；仓库禁止提交密钥、`.env`、真实患者数据、数据库卷和构建产物。
- 患者自述证据使用独立 trust level（`PATIENT_REPORTED` + `PENDING_VERIFICATION`），不得升级为 `SYSTEM_VERIFIED`。
- 每个 Finding 必须记录 `supporting_evidence` 与 `searched_sources`；“未找到记录”不得改写为“不存在”。
- 医生接受/驳回必须**追加** Audit Log，不得覆盖原始 Agent 输出。
- 工具调用受白名单、步数预算（默认 8）、超时（默认 30s）和 fallback 约束。
- 信息不足时输出“需要确认”，不自动补全临床事实。

## 4. 本地启动

前置：Docker、Python 3.12+、Node 22+。

```bash
# 1. 环境变量
cp .env.example .env

# 2. Python 依赖
python -m pip install -e .

# 3. 起数据库和事件总线
docker compose up -d postgres redis

# 4. 迁移 + 种子
alembic upgrade head
python -m packages.fixtures.seed

# 5. 起 API
make dev            # python -m uvicorn apps.api.app.main:app --reload --port 8000
```

验证：

```bash
curl http://localhost:8000/healthz
# {"status":"ok"}
```

## 5. 测试

```bash
make test            # pytest -q
make lint            # ruff check . + 前端 lint
make format-check    # ruff format --check + prettier --check
```

前端：

```bash
npm --prefix apps/web ci
npm --prefix apps/web run dev
npm --prefix apps/web run test -- --run
npm --prefix apps/web run build
```

工作台地址为 `http://127.0.0.1:5173/?patient=P-1001`。医生身份、证据抽屉、审核、交接编辑和评测说明见 [医生工作台与合成评测](docs/development/doctor-console-evaluation.md)。

### 真实 DeepSeek Agent 试用

默认 `AGENT_PROVIDER=mock`，用于无密钥的离线演示。要让 Worker 调用真实
DeepSeek 模型，请只在本机 `.env` 中设置：

```dotenv
AGENT_PROVIDER=deepseek
DEEPSEEK_API_KEY=你的本机密钥
DEEPSEEK_MODEL=deepseek-chat
EVENT_BUS=redis
```

然后按 [DeepSeek Agent 试用指南](docs/development/deepseek-agent-trial.md)
启动 PostgreSQL、Redis、API、Worker 和前端。模型只提交候选 Intent 与证据引用；
Deterministic Guard 仍负责状态合法性和高风险审核。模型调用失败时，本次事件会以
`MODEL_ERROR` 结束并保留错误码，不会自动写入临床 Finding。

## 6. Demo

主 Demo 病例 `P-1001`（`CASE-BLOOD-CULTURE`）：

```text
09:10 查房复查血培养  → 创建 FOLLOW_RESULT Open Loop
14:30 血培养阳性      → resume → RESULT_WITHOUT_ACKNOWLEDGEMENT gap
18:00 医生确认并等待药敏 → re-plan → 新依赖 Loop（等待药敏结果）
20:00 夜班交接        → Handoff 草稿纳入未闭环高优先级 Loop
```

运行：

```bash
python scripts/run_demo.py --patient P-1001
```

详细步骤见 `docs/demo/runbook.md`（任务 14）。

## 7. 评测

```bash
python -m eval.run_eval --count 100 --seed 20260928 --output artifacts/eval/report.json
```

固定 seed 生成至少 100 条合成轨迹，比较四类方法：**Direct LLM**、**RAG + Template**、**Rule Engine**、**ClinLoop**。
指标：Workflow Gap Recall、False Alarm Rate、Evidence Coverage、Handoff Omission Rate。

默认模型方法使用明确标注的离线 mock，仅验证工程链路。真实模型须显式指定 provider；默认结果不代表 LLM 或 RAG 的效果。详见 [评测说明](eval/README.md)。

## 8. Git / PR 规则

- `main` 是唯一集成分支，**禁止直接 push**。
- 分支命名：`foundation`、`feat/agent-runtime`、`feat/doctor-console-eval`、`fix/*`、`docs/*`。
- 所有变更经 PR、CI 与至少一名 reviewer 通过后 **squash merge**。
- 使用 **Conventional Commits**（`feat:` / `fix:` / `chore:` / `docs:` / `test:` / `refactor:`）。
- PR 必须包含：变更说明、测试命令与结果、接口变化、UI 截图或录屏、已知限制。
- 合并顺序：`foundation` → 两条主体 PR 并行 → `integration` → `evaluation-and-demo`。

## 9. 已知限制

- 全部为合成数据，单患者主 Demo。
- Intent taxonomy 有限（`FOLLOW_RESULT`、`FOLLOW_CONSULT`、`EXECUTE_ORDER`、`UPDATE_PLAN`）。
- 无真实 EHR / FHIR 写入，MCP Server 只读模拟数据。
- MVP 未覆盖多患者并发调度与生产级高可用。

## 10. 发布验收

```bash
python scripts/verify_release.py
```

固定 seed 的评测报告位于 `artifacts/eval/report.json`，方法对比位于
`artifacts/eval/comparison.csv`。演示和架构材料见
[`docs/demo/runbook.md`](docs/demo/runbook.md)、
[`docs/architecture/system-overview.mmd`](docs/architecture/system-overview.mmd)
和 [`docs/release/mvp-checklist.md`](docs/release/mvp-checklist.md)。
