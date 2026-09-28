# ClinLoop MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 在单仓库中实现基于合成临床事件的 ClinLoop MVP，支持 Clinical Intent、Open Loop、Evidence、Agent suspend/resume/re-plan、workflow gap、医生审核、交接草稿和可重复评测。

**Architecture:** React 医生工作台通过 FastAPI 访问 Workflow Memory；Python Worker 从 Redis Streams 消费 ClinicalEvent，调用 Python MCP Server 工具并运行 Workflow Agent；PostgreSQL 保存事件、Loop、Evidence、Finding、Run、Review、Handoff 和 Audit。Agent 只产生候选状态变化，Deterministic Guard 负责状态、权限、审核和安全边界。

**Tech Stack:** Python 3.12、FastAPI、Pydantic v2、SQLAlchemy 2、Alembic、Redis 7、PostgreSQL 16、Python MCP SDK、React 18、TypeScript、Vite、Vitest、Playwright、pytest、Ruff、ESLint、Prettier、Docker Compose、GitHub Actions。

## Global Constraints

- 只使用合成或脱敏数据；禁止提交真实患者数据、密钥、.env、数据库卷和构建产物。
- 不做自动诊断、治疗推荐、开立/修改/停止医嘱或自动关闭高风险临床任务。
- Agent 输出候选状态变化和证据绑定的 finding；不能直接写状态字段。
- 高风险状态变化必须经过 Deterministic Guard 和医生审核。
- 每个 finding 保存 supporting_evidence 和 searched_sources。
- 患者证据使用独立 trust level，例如 PATIENT_REPORTED + PENDING_VERIFICATION。
- main 禁止直接 push；所有代码经 PR、CI 和至少一名 reviewer 后 squash merge。
- 每项任务先写失败测试，再写最小实现，再运行测试，最后提交独立 commit。
- 版本目标：Python 3.12、Node 22、PostgreSQL 16、Redis 7。

## 0. 执行顺序和分工

当前起点：main 分支，已有设计提交 4866ab3，规格文件为 docs/superpowers/specs/2026-09-28-clinloop-mvp-design.md。

| 任务 | 负责人 | 分支 | 依赖 |
|---|---|---|---|
| 1–4 | 你 | foundation | 规格已确认 |
| 5–8 | 队友 A | feat/agent-runtime | foundation 合并 |
| 9–11 | 队友 B | feat/doctor-console-eval | foundation 合并，可与 A 并行 |
| 12–14 | 你 + 两位队友 | integration/evaluation-and-demo | 两条主体 PR 合并 |
| 15 | 你 | main | 所有验收通过 |

---

## 1. 仓库工具链、Docker 和 Git 门禁

**负责人：** 你  
**Files:**

- Create: .gitignore, .editorconfig, README.md, .env.example, Makefile
- Create: pyproject.toml, package.json, docker-compose.yml
- Create: .github/workflows/ci.yml, .github/workflows/security.yml
- Create: .github/pull_request_template.md, .github/CODEOWNERS
- Create: apps/__init__.py, packages/__init__.py
- Test: tests/test_tooling_contract.py

**Produces:**

- make install/test/lint/format-check/dev/seed/reset-db。
- postgres 和 redis Compose 服务及健康检查。
- backend/frontend CI。
- main 分支保护、PR 模板、CODEOWNERS 和 Conventional Commits 规则。

- [ ] 写失败测试，检查 .env.example、Makefile、pyproject.toml、package.json、docker-compose.yml、.github/workflows/ci.yml 全部存在，并检查 DATABASE_URL、REDIS_URL、API_PORT、OPENAI_API_KEY 占位符存在。
- [ ] 创建 .gitignore：包含 .env、.venv、__pycache__、node_modules、dist、coverage、postgres-data、redis-data、playwright-report。
- [ ] 创建 .env.example：

~~~dotenv
DATABASE_URL=postgresql+psycopg://clinloop:clinloop@localhost:5432/clinloop
REDIS_URL=redis://localhost:6379/0
API_PORT=8000
WEB_PORT=5173
OPENAI_API_KEY=
AGENT_PROVIDER=mock
AGENT_STEP_BUDGET=8
AGENT_TIMEOUT_SECONDS=30
~~~

- [ ] 创建 pyproject.toml，固定 Python >=3.12，依赖 FastAPI、Pydantic、SQLAlchemy、Alembic、Redis、psycopg、pytest、pytest-asyncio、httpx、uvicorn，并设置 pytest pythonpath=["."] 与 Ruff 规则 E/F/I/UP/B。
- [ ] 创建 Docker Compose：PostgreSQL 16 映射 5432，Redis 7 映射 6379，均有 healthcheck。
- [ ] Makefile 的 dev 命令使用 python -m uvicorn apps.api.app.main:app --reload --port 8000；test 运行 pytest -q；lint 运行 ruff check . 和前端 lint。
- [ ] CI 使用 setup-python 3.12、setup-node 22，运行 pytest、ruff、前端 Vitest、ESLint；security job 运行 secret scan。
- [ ] 运行：

~~~powershell
python -m pip install -e .
pytest tests/test_tooling_contract.py -q
ruff check .
git add .
git commit -m "chore: bootstrap ClinLoop monorepo tooling"
~~~

---

## 2. 冻结公共模型和状态机

**负责人：** 你  
**Files:**

- Create: packages/contracts/enums.py, models.py, api.py
- Create: packages/domain/state_machine.py, transition_policy.py, errors.py
- Test: tests/contracts/test_models.py, tests/domain/test_state_machine.py

**Produces:**

- ClinicalEvent、ClinicalIntent、OpenLoop、EvidenceNode、Finding、AgentRun、ReviewDecision、HandoffReport。
- validate_transition(current, requested, evidence_ids, clinician_approved) -> TransitionResult。
- required_review_for(requested_state) -> bool。

- [ ] 先写失败测试：RESULT_AVAILABLE 不能直接 RESOLVED；ACKNOWLEDGED → RESOLVED 无 clinician approval 时返回 allowed=False、requires_review=True；未知转换抛 InvalidTransition。
- [ ] 在 enums.py 定义 EventType：NOTE_CREATED、ORDER_UPDATED、LAB_RESULT_CREATED、CONSULT_NOTE_CREATED、PROGRESS_NOTE_CREATED、HANDOFF_STARTED、PATIENT_EVIDENCE_SUBMITTED；定义 LoopState、FindingType 和 TrustLevel。
- [ ] 所有 Pydantic 模型使用 ConfigDict(extra="forbid")；时间必须带时区；ID 非空；confidence 在 0 到 1。
- [ ] 状态机允许系统事件驱动的 ORDERED → IN_PROGRESS；要求 Evidence 的 RESULT_AVAILABLE → ACKNOWLEDGED；高风险转换必须要求审核；不执行数据库写入。
- [ ] 运行：

~~~powershell
pytest tests/contracts tests/domain -q
ruff check packages tests
git add packages tests
git commit -m "feat: define ClinLoop contracts and state policy"
~~~

---

## 3. 数据库迁移、Repository 和合成种子

**负责人：** 你  
**Files:**

- Create: apps/api/app/db.py, apps/api/app/db_models.py, apps/api/app/repositories.py
- Create: alembic.ini, infra/migrations/env.py
- Create: infra/migrations/versions/0001_initial_workflow_schema.py
- Create: packages/fixtures/cases.py, events.py, seed.py
- Test: tests/db/test_migrations.py, tests/fixtures/test_seed.py

**Produces:**

- 表：patients、encounters、clinical_events、clinical_intents、open_loops、evidence_nodes、findings、agent_runs、review_decisions、handoff_reports、audit_logs。
- get_session() -> Iterator[Session]。
- seed_demo_case("CASE-BLOOD-CULTURE") -> None。

- [ ] 先写失败测试：种子病例包含 NOTE_CREATED、LAB_RESULT_CREATED、PROGRESS_NOTE_CREATED、HANDOFF_STARTED；预期 gap 为 RESULT_WITHOUT_ACKNOWLEDGEMENT；重复 seed 不产生重复 ID。
- [ ] 创建 SQLAlchemy 表；所有核心表保存 created_at、updated_at、原始 JSON payload；建立 patient/event、patient/state、loop/observed_at、audit/entity/time 索引。
- [ ] 编写主 Demo 轨迹：09:10 查房复查血培养；14:30 结果阳性；没有 acknowledgement；18:00 医生确认并等待药敏；20:00 交接。
- [ ] seed 使用固定 ID 和事务，支持重复执行；reset-db 按 downgrade base、upgrade head、seed 执行。
- [ ] 运行：

~~~powershell
docker compose up -d postgres redis
alembic upgrade head
python -m packages.fixtures.seed
pytest tests/db tests/fixtures -q
git add apps/api/app/db.py apps/api/app/db_models.py apps/api/app/repositories.py alembic.ini infra packages/fixtures tests
git commit -m "feat: add workflow persistence and demo fixtures"
~~~

---

## 4. FastAPI 事件、Loop、Evidence 和 OpenAPI

**负责人：** 你  
**Files:**

- Create: apps/api/app/main.py, dependencies.py
- Create: apps/api/app/routes/health.py, events.py, loops.py, evidence.py
- Create: tests/api/test_health.py, test_events.py, test_loops.py

**Produces:**

- GET /healthz。
- POST /api/v1/events，重复 event_id 返回 409。
- GET /api/v1/patients/{patient_id}/timeline?hours=24。
- GET /api/v1/patients/{patient_id}/loops。
- GET /api/v1/loops/{loop_id}。
- GET /api/v1/findings/{finding_id}。
- apps/api/openapi.json。

- [ ] 先写 TestClient 失败测试：/healthz 返回 {"status":"ok"}；合法 ClinicalEvent 返回 202 和 event_id；非法事件返回 422；重复事件返回 409。
- [ ] main.py 只组装路由和生命周期；repository 负责数据库；EventPublisher 是可替换接口；API 不直接返回 SQLAlchemy 对象。
- [ ] timeline 按 event_time 排序并默认 24 小时；loop 查询返回相关 intent 和证据摘要。
- [ ] 导出 OpenAPI 并提交 foundation PR：

~~~powershell
pytest tests/api -q
python -c "from apps.api.app.main import app; import json; json.dump(app.openapi(), open('apps/api/openapi.json','w',encoding='utf-8'), ensure_ascii=False, indent=2)"
git add apps/api tests/api
git commit -m "feat: add event and workflow APIs"
git push -u origin foundation
~~~

foundation PR 只有在 CI 全绿、至少一名 reviewer 通过、main 保护规则开启后才合并。

---

# 队友 A：Workflow Agent、后端和 MCP

## 5. 事件总线、Workflow Memory 和 AgentRun

**负责人：** 队友 A  
**Branch：** feat/agent-runtime  
**Files:**

- Create: apps/worker/worker/bus.py, memory.py, repositories.py, run_models.py
- Test: tests/worker/test_bus.py, test_memory.py

**Produces:**

- EventBus.publish(event: ClinicalEvent) -> str。
- EventBus.consume(consumer_group: str, count: int = 10) -> list[ClinicalEvent]。
- WorkflowMemory.get_context(patient_id, loop_id) -> WorkflowContext。
- WorkflowMemory.save_intent/save_loop/append_evidence。
- AgentRunRepository.create/append_trace。

- [ ] 失败测试：InMemoryEventBus 保持顺序；Redis 不可用时本地实现可用；重复 event_id 不创建第二个 AgentRun。
- [ ] RedisStreamEventBus 使用 stream clinloop.events、group clinloop-workers；成功 ack，失败不 ack；消息体为 ClinicalEvent.model_dump_json()。
- [ ] WorkflowContext 只包含当前 snapshot、相关 intent/loop、最近事件、相关 evidence 和 scratchpad，禁止加载全部患者历史。
- [ ] 运行 pytest tests/worker/test_bus.py tests/worker/test_memory.py -q 并提交：

~~~powershell
git add apps/worker tests/worker
git commit -m "feat: add event bus and workflow memory"
~~~

## 6. Workflow Agent：OBSERVE 到 VERIFY 和 re-plan

**Files:**

- Create: apps/worker/worker/agent.py, planner.py, ports.py, runner.py
- Test: tests/worker/test_agent_loop.py, test_resume_replan.py

**Produces:**

~~~python
class WorkflowAgent:
    def handle_event(self, event: ClinicalEvent) -> AgentRun: ...
    def resume_loop(self, loop_id: str, event: ClinicalEvent) -> AgentRun: ...
    def replan(self, run_id: str, new_evidence: list[EvidenceNode]) -> AgentRun: ...
~~~

- [ ] 失败测试按 NOTE_CREATED → LAB_RESULT_CREATED → finding → PROGRESS_NOTE_CREATED → 新依赖 Loop → HANDOFF_STARTED 执行；断言同一 intent_id、至少两个 run_id、第二次计划变化、未审核不 RESOLVED。
- [ ] AgentStep 包含 step_id、kind、input_ref、output_ref、reason、started_at、finished_at；停止原因只能是 WAITING_EXTERNAL_EVENT、REQUIRES_CLINICIAN_REVIEW、SUFFICIENT_EVIDENCE、BUDGET_EXCEEDED、CONFLICTED_EVIDENCE。
- [ ] 实现 OBSERVE、REASON、PLAN、ACT、VERIFY 五步；PLAN 最多使用 AGENT_STEP_BUDGET；ACT 只调用 ToolRegistry，不能写状态。
- [ ] waiting_for 持久化；事件路由器按 event_type 和 payload 唤醒 Loop；resume 重新组装最小上下文。
- [ ] 运行并提交：

~~~powershell
pytest tests/worker/test_agent_loop.py tests/worker/test_resume_replan.py -q
git add apps/worker tests/worker
git commit -m "feat: implement workflow agent loop and replanning"
~~~

## 7. MCP Server、工具白名单和临床 Skills

**Files:**

- Create: apps/mcp_server/mcp_server/server.py, tools.py, adapters.py, schemas.py
- Create: apps/worker/worker/skills/intent.py, normalize.py, temporal.py, matching.py, verification.py
- Test: tests/mcp_server/test_tools.py, test_tool_registry.py, tests/worker/test_skills.py

**Produces:**

- get_patient_snapshot、get_recent_events、get_orders、get_labs、get_consults、get_progress_notes、get_handoff、get_patient_evidence、record_review_decision、seal_handoff_report。
- extract_clinical_intent、normalize_clinical_event、match_intent_to_execution、verify_workflow_continuity。

- [ ] 失败测试：未知患者抛 PatientNotFound；读工具不修改数据；Registry 拒绝未知工具；review 只追加 Audit；未审核 handoff 不能 seal。
- [ ] 工具通过 repository 读取合成数据，不执行任意 SQL/文件访问；每个输入和输出使用 contracts 类型或只读 DTO。
- [ ] 有限 taxonomy 支持 FOLLOW_RESULT、FOLLOW_CONSULT、EXECUTE_ORDER、UPDATE_PLAN；“今天复查血培养，结果出来后再决定下一步”提取 FOLLOW_RESULT 和 blood_culture_result。
- [ ] 解析“今天/今晚/明日”为带时区窗口；无法解析返回 None；不猜测。
- [ ] 运行 pytest tests/mcp_server tests/worker/test_skills.py -q 并提交：

~~~powershell
git add apps/mcp_server apps/worker tests
git commit -m "feat: add MCP tools and clinical workflow skills"
~~~

## 8. Verifier、Guard、Review/Audit/Handoff API

**Files:**

- Create: packages/domain/verifier.py, guard.py
- Create: apps/api/app/routes/findings.py, audit.py, handoff.py
- Create: apps/api/app/services/review_service.py, audit_service.py, handoff_service.py
- Test: tests/domain/test_guard.py, test_verifier.py, tests/api/test_review.py, test_handoff.py, test_audit.py

**Produces:**

- Guard.apply(candidate_state_change, reviewer) -> GuardResult。
- POST /api/v1/findings/{finding_id}/review。
- GET /api/v1/loops/{loop_id}/trace。
- GET /api/v1/patients/{patient_id}/audit。
- POST /api/v1/patients/{patient_id}/handoff/draft。
- POST /api/v1/handoff/{handoff_id}/seal。

- [ ] 失败测试：无 evidence 不能提交；PATIENT_REPORTED 不能升级 SYSTEM_VERIFIED；ACKNOWLEDGED → RESOLVED 无 reviewer 被拒绝；已封存 handoff 不可编辑；驳回不删除原 finding。
- [ ] Verifier 比较 Plan、Order、Execution、Result、Response、Handoff，输出 status、finding_type、supporting_evidence、searched_sources、requires_review；“未找到记录”不能改写为“不存在”。
- [ ] Handoff 只使用已确认 Evidence、已标注的 PENDING_REVIEW finding 和全部高优先级未闭环 Loop，并区分已确认事实和待确认事项。
- [ ] Audit append-only，记录 actor、时间、旧状态、新状态、reason、source run id；不提供 update/delete。
- [ ] 运行后提交 Agent PR：

~~~powershell
pytest tests/domain tests/api tests/mcp_server tests/worker -q
git fetch origin
git rebase origin/main
git push -u origin feat/agent-runtime
~~~

---

# 队友 B：医生端、交接和评测

## 9. React 医生工作台骨架

**负责人：** 队友 B  
**Branch：** feat/doctor-console-eval  
**Files:**

- Create: apps/web/package.json, index.html, vite.config.ts, tsconfig.json
- Create: apps/web/src/main.tsx, App.tsx, api/client.ts, api/types.ts
- Create: apps/web/src/test/setup.ts, src/App.test.tsx

**Produces:**

- ApiClient.listTimeline、listLoops、getFinding、reviewFinding、createHandoffDraft。
- Vite、Vitest、ESLint、Prettier、TypeScript 配置。

- [ ] 失败测试：App 渲染 Patient Timeline、Open Loops、Workflow Gaps、Agent Trace、Handoff Draft。
- [ ] 初始化 scripts：dev、build、test、lint、format、format:check。
- [ ] client 使用 VITE_API_BASE_URL（默认 http://localhost:8000），非 2xx 抛 ApiError；组件禁止直接 fetch。
- [ ] App 支持 query patient=P-1001；请求失败显示重试；无数据显示空态。
- [ ] 运行 npm --prefix apps/web run test -- --run、lint、build 并提交基础前端。

## 10. 五个工作台视图和审核交互

**Files:**

- Create: PatientTimeline.tsx、OpenLoopsPanel.tsx、WorkflowGapsPanel.tsx、AgentTracePanel.tsx、HandoffDraftPanel.tsx
- Create: EvidenceDrawer.tsx、ReviewDialog.tsx、usePatientWorkflow.ts、workspace.css
- Test: WorkflowGapsPanel.test.tsx、HandoffDraftPanel.test.tsx

- [ ] 失败测试：Accept 调用 reviewFinding(ACCEPT) 并显示成功；Reject 必须有非空 reason；finding 原始 claim/evidence 保留。
- [ ] Timeline 展示 event_time、source、actor；Loop 展示 state、waiting_for、owner、next_check；Gap 展示 finding type、claim、supporting evidence、searched sources。
- [ ] EvidenceDrawer 可从 evidence ID 回到原始记录；PATIENT_REPORTED 有单独徽标。
- [ ] Agent Trace 展示 step、tool、reason、时间、output reference、stop reason，ACT 参数默认折叠。
- [ ] Handoff 只能编辑草稿文本和备注，不能改 evidence IDs、loop IDs、sealed 状态；有未审核高风险事项时禁用封存。
- [ ] 运行前端 test、lint、build，提交：

~~~powershell
git add apps/web
git commit -m "feat: add clinician workflow console"
~~~

## 11. 合成轨迹、回放器、Baseline 和指标

**Files:**

- Create: eval/generators/cases.py, defects.py
- Create: eval/replay/replayer.py
- Create: eval/baselines/direct_llm.py, rag_template.py, rule_engine.py
- Create: eval/metrics/definitions.py, report.py, eval/run_eval.py
- Test: tests/eval/test_generator.py, test_replay.py, test_metrics.py

**Produces:**

~~~python
generate_cases(count: int, seed: int) -> list[SyntheticCase]
inject_defect(case: SyntheticCase, defect_type: FindingType, seed: int) -> SyntheticCase
replay(case: SyntheticCase, handler: EventHandler) -> ReplayResult
compute_metrics(expected, actual) -> MetricsReport
run_all_methods(cases) -> ComparisonReport
~~~

- [ ] 失败测试覆盖 Workflow Gap Recall、False Alarm Rate、Evidence Coverage、Handoff Omission Rate；分母为 0 返回 0.0。
- [ ] 固定 seed 生成至少 100 条：25 正常、20 Plan→Order、20 Order→Execution、20 Result→Response、15 Evidence→Handoff。
- [ ] Replay 记录 run、tool calls、最终状态；相同 seed 输出稳定，比较时忽略 UUID 和 wall-clock duration。
- [ ] 四类方法统一返回 FindingPrediction/HandoffPrediction：Direct LLM、RAG + Template、Rule Engine、ClinLoop。
- [ ] 运行：

~~~powershell
python -m eval.run_eval --count 100 --seed 20260928 --output artifacts/eval/report.json
pytest tests/eval -q
git add eval tests/eval
git commit -m "feat: add replay evaluation and baseline comparison"
git push -u origin feat/doctor-console-eval
~~~

---

## 12. 合并两条主体 PR 并完成端到端联调

**负责人：** 你  
**Files:**

- Create: tests/integration/test_demo_flow.py, scripts/run_demo.py
- Create: docs/architecture/runtime-sequence.md
- Modify: docker-compose.yml, Makefile, apps/api/app/main.py

- [ ] 在最新 main 创建 integration 分支，先合并 Agent PR，再合并 Doctor Console/Eval PR；每次合并前 CI 全绿且 reviewer 批准。
- [ ] 失败测试断言：NOTE_CREATED 创建 FOLLOW_RESULT；LAB_RESULT_CREATED 产生 RESULT_WITHOUT_ACKNOWLEDGEMENT；finding 能回到 LAB-8821；PROGRESS_NOTE_CREATED 关闭原响应阶段并创建等待药敏的新 Loop；HANDOFF_STARTED 纳入新 Loop；未 review 不 RESOLVED；Audit 至少有 run/review/seal。
- [ ] scripts/run_demo.py --patient P-1001 依次发布 fixture 事件，等待 run 完成并打印 event_id、run_id、loop_ids、findings、final_action。
- [ ] 运行：

~~~powershell
docker compose up -d
alembic upgrade head
python -m packages.fixtures.seed
pytest tests/integration -q
python scripts/run_demo.py --patient P-1001
git add apps scripts tests/integration docker-compose.yml Makefile docs/architecture
git commit -m "feat: integrate end-to-end ClinLoop demo"
~~~

---

## 13. 稳定性、预算、超时和安全边界

**负责人：** 你 + 队友 A  
**Files:**

- Create: apps/worker/worker/policies.py, apps/api/app/middleware.py
- Create: tests/security/test_safety_boundaries.py, tests/worker/test_budget_fallback.py
- Modify: apps/worker/worker/agent.py, packages/domain/guard.py
- Create: docs/security/mvp-boundaries.md

- [ ] 失败测试证明：未注册工具不能调用；LLM 输出不能直接写状态；PATIENT_REPORTED 不能升级；已封存 handoff 不可编辑；无 reviewer 不能 RESOLVED；工具超时有 stop reason。
- [ ] ExecutionPolicy.max_steps 默认 8，timeout_seconds 默认 30；超时记录工具名、参数摘要和错误码，不解释为“未找到”。
- [ ] 达到 budget 时保存已完成 tool calls，生成 BUDGET_EXCEEDED，不提交新的状态，转为 candidate finding 或等待。
- [ ] 任何异常追加 Audit Log；日志不输出患者原始文本或 API key。
- [ ] 运行 pytest tests/security tests/worker/test_budget_fallback.py -q，执行 rg secret scan，再提交 fix: enforce runtime safety boundaries。

---

## 14. 主 Demo、架构图和比赛材料

**负责人：** 你 + 两位队友  
**Files:**

- Create: docs/demo/runbook.md, demo-script.md, sample-output.md
- Create: docs/architecture/system-overview.mmd, agent-sequence.mmd
- Create: artifacts/eval/report.json, artifacts/eval/comparison.csv
- Create: scripts/check_demo_ready.py
- Test: tests/demo/test_demo_ready.py

- [ ] 失败测试检查病例可加载、至少两次 Agent run、一次 re-plan、至少一个 finding、handoff 包含高优先级 Loop、报告包含四种方法。
- [ ] runbook 写明干净启动、数据重置、Demo 命令、页面地址、P-1001、预期状态和固定 seed 重放方法。
- [ ] Mermaid 图展示 Event Stream → API → Worker → MCP → Workflow Memory → Guard → Doctor Review → Web，以及 OBSERVE→REASON→PLAN→ACT→VERIFY。
- [ ] 生成并冻结报告：

~~~powershell
python -m eval.run_eval --count 100 --seed 20260928 --output artifacts/eval/report.json
python scripts/check_demo_ready.py
pytest tests/demo -q
~~~

- [ ] 提交 docs、artifacts、scripts 和 tests，commit message 为 docs: package ClinLoop demo and evaluation evidence。

---

## 15. 最终验收、发布和标签

**负责人：** 你  
**Files:**

- Modify: README.md
- Create: CHANGELOG.md, docs/release/mvp-checklist.md
- Create: scripts/verify_release.py
- Test: tests/release/test_release.py

- [ ] checklist 必须明确覆盖 6 类事件、4 类 gap、两次 suspend/resume、一次 re-plan、原始证据回跳、医生确认和四类方法。
- [ ] README 包含产品边界、安全声明、架构、本地启动、测试、Demo、评测、Git/PR 规则和已知限制。
- [ ] 运行完整验证：

~~~powershell
docker compose down -v
docker compose up -d
python -m pip install -e .
npm install
alembic upgrade head
python -m packages.fixtures.seed
python scripts/verify_release.py
~~~

- [ ] verify_release 必须运行后端测试、前端测试/lint/build、integration、eval、security scan；全部成功才返回 0。
- [ ] 创建 release/v0.1.0-mvp PR，CI 和 reviewer 通过后 squash merge；在最新 main 创建并推送标签 v0.1.0-mvp。
- [ ] CHANGELOG 记录发布范围、seed、轨迹数量、报告路径和限制：合成数据、单患者主 Demo、有限意图 taxonomy、无真实 EHR 写入。

## 合并门禁

### foundation PR

- [ ] 任务 1–4 通过。
- [ ] Docker、迁移、种子、OpenAPI 均可重复运行。
- [ ] 公共契约和状态机已冻结。
- [ ] 无密钥、真实数据、未跟踪产物。

### Agent PR

- [ ] Redis/内存 EventBus、两次 resume、一次 re-plan、动态工具选择通过测试。
- [ ] Guard 阻止未经审核的高风险状态。
- [ ] Finding 有 evidence 和 searched_sources。
- [ ] Review、Audit、Handoff 有集成测试。

### Doctor Console/Eval PR

- [ ] 五个视图、证据跳转、Accept/Reject/封存交互通过测试。
- [ ] 100+ 固定 seed 轨迹。
- [ ] 四类方法统一指标接口。

### 发布前

- [ ] event → resume → tool use → finding → review → re-plan → handoff 全链路通过。
- [ ] 所有 release checks 返回 0。
- [ ] CI、secret scan、后端、前端和构建均通过。
- [ ] v0.1.0-mvp 指向最终合并提交。

