# AgentArts 发布工作流部署手册

状态（2026-10-08）：已在西南-贵阳一创建并试运行任务型工作流，提交版本 `v1-clinloop-sop-review`；正式部署和发布运行时 API 调用仍待完成。工作流 ID `7fd9dec4-4c6d-4436-af00-23bac248a2e9`，知识库 ID `ae1d0dfd6c3e408ba9147f72b50e073e`。另已创建多智能体控制器草稿 `ClinLoop-CareLoop-Review-v1`，ID `9fa7bcb7-9cb9-4a29-9f2e-b0134702a14c`；它尚未试运行或部署。以下变量名是 ClinLoop 适配器的接口契约。所有输入仅使用合成病例。

## 账号与区域

1. 开通智果 AgentArts，确认区域、模型额度、可用的运行时鉴权方式。参照 [官方创建工作流](https://support.huaweicloud.com/lowcode-agentarts/agentarts_05_0047.html) 和 [发布部署](https://support.huaweicloud.com/lowcode-agentarts/agentarts_05_0053.html)。
2. 在平台知识库上传 [knowledge-sop-v1.md](knowledge-sop-v1.md)，记录知识库版本和分段设置。不要上传评测题目、答案或真实患者数据。
3. 建立任务型工作流 `ClinLoop-Result-Followup-v1`。当前开始节点保留平台默认的 String `query`，另有 String `context_json`、`schema_version`、`request_id`、`patient_id`、`trigger_event_id`。适配器把同一个序列化 AgentContext 送入 `query` 和 `context_json`；平台显示前两者为可选，但后续节点已引用，因此 API 调用必须提供两者。`schema_version` 固定 `1.0`。后两个字段供 HTTP 工具节点直接引用，ClinLoop API 会再用触发事件校验患者归属。

## 编排

画布已连入：开始 → 知识检索 → 意图提案大模型 → 证据复核大模型 → 结束。知识检索 query 使用固定概念问题“检验结果随访意图、结果确认、证据来源与安全边界”，`output_list` 被意图模型的 `sop_context` 参数引用。画布还保留开始 → 意图模型的直接连线，但意图模型通过 `sop_context` 依赖检索结果；2026-10-08 的平台调用详情显示检索和两个模型节点均成功执行。模型节点当前为 `DeepSeek-V4-Flash` 文本输出，提示词要求纯 JSON。正式多智能体应用须单独创建，不能把两个 LLM 节点冒称为已部署的多智能体。

平台试运行记录：合成输入 `P-SYN-1` / `EVT-TEST-1`，首次运行暴露 `priority=high` 的契约错误；修正两个节点提示词后，同一输入于 2026-10-08 19:12:40（中国时间）再次成功，耗时 15.42 秒。最终候选输出 `intent_type=FOLLOW_RESULT`、`priority=NORMAL`、`evidence_refs=["EVT-TEST-1","NOTE-TEST-1"]`。这是单例调试，不代表 50 例在线评测或临床效果。

意图提案节点系统提示词：

```text
你是合成病例工作流意图识别员。只分析输入 context_json 中当前时刻可见的记录及检索到的流程 SOP。只输出 JSON 对象，不输出 Markdown。识别是否存在明确的检验结果随访要求。不得诊断、处方或推断缺失记录必然不存在。patient_id 必须原样复制。无明确意图时 intent_type 设为 null。任何 evidence_refs 只能引用 context_json 中已有的 event_id、payload_ref 或 evidence_id。requested_tools 只允许 get_patient_snapshot、get_recent_events、get_orders、get_labs、get_consults、get_progress_notes、get_handoff、get_patient_evidence。不得请求写工具。
输出字段必须完整：patient_id, intent_type, goal, rationale, expected_evidence, waiting_for, priority, confidence, evidence_refs, requested_tools。
priority 只能是大写 LOW、NORMAL、HIGH、CRITICAL；intent_type 和 waiting_for 也必须使用契约中的大写枚举。当前 event 的 event_id 和 payload_ref 即使 visible_evidence 为空，仍可作为当前可见记录引用。
FOLLOW_RESULT 意图的血培养预期证据使用 blood_culture_result，等待事件使用 LAB_RESULT_CREATED。无意图则 expected_evidence、waiting_for 和 evidence_refs 为空数组。
```

证据复核节点系统提示词：

```text
你是独立的工作流证据复核员。核对上一节点 JSON 与原始 context_json、流程 SOP。只保留同一患者、当前可见且可追溯的引用。检验项目不一致时，不要宣称意图完成；缺少确认记录只能表述为“已搜索记录中未找到”。如上一步臆造引用或目标，修正为保守提案，降低 confidence。只输出与上一节点相同字段的完整 JSON 对象，不输出其他文字。不得诊断、处方或写入病历。
priority 只能是大写 LOW、NORMAL、HIGH、CRITICAL；intent_type 和 waiting_for 也必须使用契约中的大写枚举。当前 event 的 event_id 和 payload_ref 属于可见记录，不因 visible_evidence 为空而丢弃。
```

结束节点采用任务型 JSON 输出，把复核节点完整 JSON 对象序列化为 `proposal_json` 字符串。发布后用官方 [InvokeRuntime](https://support.huaweicloud.com/api-agentarts/InvokeRuntime.html) 测试响应是否在 `data.text` 中包含提案 JSON（或包含 `proposal_json` 的 JSON 包装对象）；ClinLoop 解析器接受 JSON 与有 `node_end` 结束消息的 SSE。若当前区域 API 响应格式不同，应根据实际响应增补契约测试后再部署。

## 工具编排

可选的 HTTP 请求节点用于从公开 HTTPS ClinLoop API 读取事件证据。按 [官方 HTTP 节点](https://support.huaweicloud.com/lowcode-agentarts/http_node.html) 配置 POST `https://<demo-host>/api/v1/agentarts/tools/get_labs` 和 `get_progress_notes`，Header `X-ClinLoop-Tool-Key` 使用平台安全配置；Body 将开始节点的 `patient_id`、`trigger_event_id` 引用为同名字段。API 进程也要设置相同的 `AGENTARTS_TOOL_KEY`。API 根据触发事件固定时间边界，拒绝跨患者和写工具。不要把密钥写在画布截图、仓库或分享帖里。HTTP 节点最多等待 50 秒，生产配置须设置失败分支并让模型退回不确定结论。当前仓库的 `apps/mcp_server` 只是本地工具注册器，不是可供云平台连接的 MCP 服务；比赛演示将此处称为 HTTP 工具编排。

## 发布与本地接入

完成试运行、提交版本、部署运行时并选 API Key 鉴权。部署页另要求 MaaS 模型 API Key，且明确提示调测/试运行的免费 Tokens 不覆盖部署后的 API 调用；部署可能按量收费。日志 LTS、指标 AOM、调用链 APM 在部署页默认开启且可能计费，若不需要请关闭。2026-10-08 已在部署表单关闭这三项，但尚未完成部署。把控制台“调用路径”中的基础 URL 与 `agent-arts-...` 运行时名称分别填入环境变量；不要把整条调用路径填入 `AGENTARTS_ENDPOINT`。

```powershell
$env:AGENT_PROVIDER="agentarts"
$env:AGENTARTS_ENDPOINT="https://<AgentArts-API-host>"
$env:AGENTARTS_RUNTIME_NAME="agent-arts-<published-runtime-id>"
$env:AGENTARTS_API_KEY = Read-Host "AgentArts API Key" -AsSecureString | ConvertFrom-SecureString -AsPlainText
$env:AGENT_TIMEOUT_SECONDS="45"
uv run python scripts/run_worker.py
```

API 和前端启动参照 [本地试用](../development/deepseek-agent-trial.md)，两者保持同一数据库。Worker trace 应显示 `agentarts · agent-arts-...`，并保留请求耗时、只读工具调用、Guard 结果和安全错误码。只有真实发布运行时产生的 trace 才作为参赛平台证据。

## 多智能体展示

已在平台创建控制器草稿，将结果随访任务工作流加入子工作流，控制器模型选 `DeepSeek-V4-Flash`，将对话历史设为 0 轮、最大跳转设为 2 次，限定只接收合成病例的结构化随访请求。画布也将同一工作流设为默认工作流；这会让未识别请求落入结构化工作流，因此发布前必须改成安全兜底流程或移除默认路由并验证拒绝行为。当前只有一个子工作流，不能称作已验证的多 Agent 协作。

[官方多智能体配置](https://support.huaweicloud.com/lowcode-agentarts/agentarts_05_0106.html) 将已发布并部署工作流列为前提。正式演示还需部署子工作流、增加职责不同的子单元、在平台试运行中核对路由和调用详情，然后提交多智能体版本。ClinLoop Worker 的自动化接口仍调用上面的结构化任务工作流；多智能体演示不能替代 Worker 的 50 例契约测试。
