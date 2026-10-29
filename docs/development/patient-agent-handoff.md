# 患者工作台与临床文书 Agent：队友接手说明

日期：2026-10-27。功能分支：`codex/patient-agent-clinical-workflow`。

这次改动将原来的事件链演示接入患者日常工作台：医生选择患者，记录问诊或查房对话，由 Agent 撰写独立临床文书，医生审核签署后提取候选任务，再沿用原有检验事件、证据核验、医生确认与交班流程。所有初始化及验证资料均为模拟数据。

## 功能变化

| 模块 | 新增行为 |
| --- | --- |
| 患者目录与概况 | 六位幂等导入的模拟患者；姓名、性别、民族、年龄、婚姻状况、出生地、职业、入院时间；支持创建模拟患者。 |
| 页面导航 | 侧栏保留患者列表和患者概览；概览中的功能卡片进入独立页面，子页面提供返回入口，URL 支持直接打开与前进后退。 |
| 问诊与查房 | 浏览器实时语音转录、手动输入及粘贴；原始对话独立保存，按患者和就诊隔离。 |
| 临床文书 | 支持入院病历、查房记录、病程记录；真实模型综合对话、基本资料、已有检查和既往文书撰写正文。原文、叙述来源、信息缺失及冲突单独保留。 |
| 医生审核 | 草稿可修改；Agent 草稿必须填写签名并勾选确认才能提交，提交后锁定。重新撰写生成新版本，保留旧文书。 |
| 首次查房提醒 | 按本次产品规则，以入院时间加48小时为签署截止；逾期未签署自动产生高优先级待办，签署后自动关闭。 |
| Agent 任务 | 签署后从诊疗计划提取候选；医生确认后建立任务，检验到达唤醒原有 Worker，医生核对结果后闭环，可继续跟进药敏。 |
| 失败处理 | 页面直接显示最近生成状态和打开入口；支持从已保存原文重试。结构、来源或数值校验失败时给模型一次修正机会，仍不合格则明确失败。 |

已修复“主治医生”“住院医师”“主任医师”“主治医生（对住院医师）”等称呼未被识别、导致诊疗计划被拦截的问题。提问仍与确认事实分开处理。

## 队友如何启动和验收

在仓库根目录安装 README 中的 Python 与前端依赖，将 `.env.example` 复制为本机 `.env`，使用本地 SQLite：

```powershell
$env:DATABASE_URL = "sqlite+pysqlite:///clinloop-local.sqlite3"
uv run python -m scripts.init_product_demo
```

已有 Alembic 管理的数据库先运行 `uv run python -m alembic upgrade head`。这次新增迁移 `0003_clinical_documents`，用于保存文书及原始对话。

分别开启三个终端，均进入仓库根目录：

```powershell
# 终端1：API
$env:DATABASE_URL = "sqlite+pysqlite:///clinloop-local.sqlite3"
$env:EVENT_BUS = "database"
uv run uvicorn apps.api.app.main:app --host 127.0.0.1 --port 8001
```

```powershell
# 终端2：Worker，使用同一个数据库
$env:DATABASE_URL = "sqlite+pysqlite:///clinloop-local.sqlite3"
$env:EVENT_BUS = "database"
$env:AGENT_PROVIDER = "mock"
uv run python -m scripts.run_worker
```

```powershell
# 终端3：前端
$env:VITE_API_BASE_URL = "http://127.0.0.1:8001"
npm --prefix apps/web run dev -- --host 127.0.0.1
```

打开 `http://127.0.0.1:5173/?patient=P-2001&view=overview`。进入“病历与查房”，填写医生 ID 和角色，输入带“医生：/主治医生：/患者：”标记的合成对话，选择文书类型及撰写方式。

- 真实病历撰写：在本机 `.env` 填写 `NOTE_DRAFT_PROVIDER=deepseek`、`DEEPSEEK_API_KEY`，并核对 `DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL`；修改后重启 API 与 Worker。
- 文书格式演示：选择“文书格式演示（本地模板）”，无需模型密钥，页面明确标识未调用模型。
- 病历撰写与任务分析独立配置：`AGENT_PROVIDER=mock` 时，正式病历撰写仍可使用 DeepSeek；任务分析则为确定性规则演示。需要真实任务推理时再配置 `AGENT_PROVIDER=deepseek`。

建议验收顺序：保存对话 → 打开最新病历 → 对照依据修改 → 医生签署 → 患者 Agent 助手确认候选 → 发送模拟检验结果 → 查看原始结果并填写处理说明 → 确认闭环。

## 接口和数据变化

- `ClinicalDocumentRow` 保存 DRAFT/SUBMITTED 文书及不可修改的 INTERVIEW 原始对话，使用 revision 防止覆盖其他窗口的修改。
- 新增 `INTERVIEW_SAVED` 事件，经事务 Outbox 触发后台撰写；文书签署后才发布正式文书事件并写入医生确认的证据。
- 新增患者目录、文书、跟进任务、对话、重新撰写、首次查房状态、模型配置状态及患者 Agent 审核接口；完整契约见 `apps/api/openapi.json`。
- 查房提醒使用原有 Open Loop 保存，后台定时扫描不依赖浏览器打开；该系统待办只能随签署记录自动完成。
- 新格式文书仅从医生已审核的“诊疗计划”提取候选任务，附带检查资料及缺失提示不作为新的医嘱。

建议评审入口：`clinical_note_workflow.py`（资料范围与生成过程）、`clinical_writing.py`（真实模型、来源校验与修正）、`round_reminder_service.py`（首次查房规则）、`document_agent.py`（候选任务）、`PatientRecords.tsx` 与 `InterviewComposer.tsx`（医生操作）。

## 验证证据与限制

提交前执行后端 pytest、Ruff，前端单元测试、构建、ESLint、Prettier 检查；具体结果记录在 PR。

本地浏览器验证了页面跳转、移动端布局、原文保存、独立文书、签署锁定、提醒关闭及任务闭环；真实 DeepSeek 已用模拟患者验证入院病历和查房记录生成。语音转录界面使用模拟识别事件验证，未验证真实麦克风录音效果。

![林晓禾模拟查房文书、原始对话与医生审核界面](screenshots/patient-agent-clinical-record.png)

- 浏览器语音识别依赖浏览器、网络、中文识别支持及麦克风权限；仅保存文字，没有录音文件或自动说话人分离。
- 模型读取本次就诊最近30天最多20条检验和生成请求前最近10份已提交文书；来源、数值和结构检查不代表语义与医学内容已核实，须医生审核。
- 未配置模型时保存原文并明确失败，不将模板冒充模型结果；密钥、实际数据库、本机转录记录和日志均不进入版本库。
- 医生身份仍为原型身份头及署名确认，尚未接生产认证、医院电子签名或真实 EHR。
- 提醒展示在平台内；没有短信、微信或后台通知推送。后台扫描以现有单 Worker 运行方式验证。
- AgentArts 的临床文书撰写器尚未接入；原有 AgentArts 工作流适配器保留。

后续迭代可在此 PR 逐行评论，先评审来源范围、签署边界和候选任务，再讨论文书质量、转录体验及生产接入。
