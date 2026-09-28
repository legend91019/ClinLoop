# ClinLoop MVP 开发设计规格

- 日期：2026-09-28
- 来源：ClinLoop 华为 ICT 大赛系统设计文档 v0.1
- 状态：已通过初步设计确认
- 目标：为 coding agent 提供可执行的单仓库开发边界、接口和协作规则。

## 1. 产品范围

ClinLoop MVP 是一个事件驱动、可暂停和恢复的住院临床工作流连续性 Agent。系统持续追踪医生提出的 Clinical Intent，在医嘱、执行、结果、医生响应和交接之间建立可审计的证据链。

MVP 只使用合成或脱敏数据，覆盖晨间查房到夜班交接的单患者工作流。系统不做自动诊断、治疗推荐、开立或修改医嘱，也不把模型推断直接写入正式病历。

必须覆盖：

- 至少 6 类临床事件。
- 至少 4 类 workflow gap。
- Clinical Intent、Open Loop、Evidence、Finding、AgentRun、ReviewDecision、HandoffReport。
- 一次轨迹中的两次 suspend/resume 和一次 re-plan。
- Agent Trace、医生审核、不可覆盖 Audit Log。
- 可重复的 Direct LLM、RAG + Template、Rule Engine、ClinLoop 四类方法评测。

## 2. 技术方案

采用单仓库模块化架构：

- 前端：React + TypeScript。
- 业务 API：FastAPI + Pydantic。
- Agent Worker：Python，负责事件唤醒和 Agent run。
- MCP：Python MCP Server，封装模拟 FHIR/JSON 数据。
- 数据库：PostgreSQL。
- 事件总线：MVP 使用 Redis Streams；允许本地测试使用进程内队列。
- 评测：Python 生成、回放和计算指标。
- 本地运行：Docker Compose。

目录边界：

```text
apps/api/          FastAPI 路由和应用服务
apps/worker/       事件消费和 Workflow Agent
apps/mcp-server/   只读模拟临床数据工具
apps/web/          React 医生工作台
packages/contracts/共享 Pydantic/JSON Schema 契约
packages/domain/  状态机、Guard、领域规则
packages/fixtures/合成病例、事件和缺陷
eval/              轨迹生成、回放、baseline、指标
infra/             Compose、迁移、初始化脚本
docs/              架构、API、开发和演示说明
```

## 3. 核心数据和接口

公共契约必须先于主体功能冻结。至少包括：

- `ClinicalEvent`：`event_id`、`patient_id`、`encounter_id`、`event_type`、`event_time`、`source_time`、`payload_ref`、`actor`。
- `ClinicalIntent`：意图文本、意图类型、期望证据、来源事件、是否需要医生审核。
- `OpenLoop`：目标、状态、等待事件、依赖、负责人、上次计划、置信度。
- `EvidenceNode`：来源类型、来源 ID、观察时间、claim、provenance、trust level。
- `Finding`：gap 类型、claim、支持证据、searched sources、审核状态。
- `AgentRun`：触发事件、关联 Loop、计划、工具调用、findings、最终动作。
- `ReviewDecision`：接受/驳回/修改、审核人、时间、理由。
- `HandoffReport`：I-PASS/SBAR 草稿、来源 Loop、证据、封存状态。

允许的 Loop 状态包括：

```text
CREATED -> PLANNED -> ORDERED/ACTION_REQUESTED -> IN_PROGRESS
-> RESULT_AVAILABLE -> ACKNOWLEDGED -> RESOLVED

异常或等待态：
WAITING_EVENT、OVERDUE、ORPHANED、CONFLICTED、STALE、PENDING_REVIEW
```

LLM 不得直接写入状态字段。Agent 只产生候选状态变化和证据；Deterministic Guard 校验合法转换、审核要求和权限。

## 4. 服务边界

### 4.1 你负责的基础层

你先完成基础仓库、开发环境、CI、公共契约、数据库迁移、状态机、合成种子、启动命令和 GitHub 规则。基础层完成后，任何队友都能从最新 `main` 启动、测试并调用公共接口。

### 4.2 队友 A：Agent、后端、MCP

队友 A 负责事件摄取、Redis 唤醒、Workflow Memory、Agent Loop、动态工具调用、suspend/resume/re-plan、MCP 工具、Verifier、Guard、Review/Audit API 和 Agent Trace。

### 4.3 队友 B：医生端、交接、评测

队友 B 负责五个医生工作台视图、证据跳转、审核交互、Handoff Draft、合成轨迹生成、事件回放、三类 baseline、指标和演示数据。

两条主体分支只通过 packages/contracts 中定义的类型和 API 协作。

## 5. Git 协作

- 远程仓库：`https://github.com/legend91019/ClinLoop`。
- `main` 是唯一集成分支，禁止直接 push。
- 分支命名：`foundation`、`feat/agent-runtime`、`feat/doctor-console-eval`、`fix/*`、`docs/*`。
- 所有变更经 PR 合并，由仓库维护者最终审核和 squash merge。
- PR 必须提供变更说明、测试命令和结果、接口变化、UI 截图或录屏、已知限制。
- 禁止提交密钥、`.env`、真实患者数据、数据库卷和本地构建产物。
- 使用 Conventional Commits。
- 合并顺序：foundation → 两条主体 PR 并行 → integration → evaluation-and-demo。

## 6. 里程碑和验收

1. 基础层：干净环境可以启动服务、迁移数据库、导入种子并运行测试。
2. 数据与状态骨架：公共实体可持久化，非法状态转换会被拒绝。
3. Agent + MCP：事件可以唤醒 Agent，Agent 能动态选择工具并等待外部事件。
4. Verifier + Handoff：gap 有证据覆盖，医生审核和审计有效，交接草稿完整。
5. 评测与演示：至少 100 条可重复轨迹，四类方法可比较，主 Demo 稳定。

最终主 Demo 必须展示：

```text
查房输入 → 创建 Open Loop → 新检验事件
→ Agent resume → 动态调查 → workflow gap
→ 医生审核/补充 → re-plan → 新依赖 Loop
→ 夜班交接草稿 → 审计轨迹
```

## 7. 安全边界

- 全部数据为合成或脱敏数据，并在 Demo 中标注“工程验证，不构成临床有效性证明”。
- 患者提交证据的 trust level 必须与系统验证证据区分。
- finding 必须记录 searched_sources，不能把“未找到”表述成“不存在”。
- 医生接受或驳回必须追加 Audit Log，不能覆盖原始 Agent 输出。
- 工具调用必须有白名单、步数预算、超时和 fallback。
- 信息不足时输出需要确认，不自动补全临床事实。

