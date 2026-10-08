# AgentArts 免费试运行观测（2026-10-08）

本记录只包含合成病例。平台区域为西南-贵阳一，工作流为 `ClinLoop-Result-Followup-v1`（ID `7fd9dec4-4c6d-4436-af00-23bac248a2e9`），已提交版本为 `v1-clinloop-sop-review`。画布使用 `ClinLoop-Followup-SOP-v1` 知识库和两个 `DeepSeek-V4-Flash` 模型节点。以下输入来自仓库的 `contest-v1` 冻结合成集，并以 `AgentContext` JSON 同时填入试运行的 `query` 与 `context_json`；`schema_version=1.0`，其他 ID 字段与触发事件一致。

同日重新运行规则基线，50 例为 TP=19、FN=6、FP=0、TN=25，语料 SHA-256 为 `b8780d14be703102e22c196706308a279e030ca2a4eb24d73d21b507f21dcd90`。该基线与下述两次平台试运行是不同的测评层级。

| 样本 | 冻结标签 | 平台开始时间（中国时间） | 运行结果 | 总耗时 | 最终意图 | 引用 |
| --- | --- | --- | --- | ---: | --- | --- |
| `CONTEST-001`，血培养结果出来以后请通知我。 | 应报告 | 2026-10-08 21:32:09 | 成功 | 17.90 秒 | `FOLLOW_RESULT` | `EVT-CONTEST-001-NOTE` |
| `CONTEST-026`，查房记录：继续观察体温。 | 不应报告 | 2026-10-08 21:44:52 | 成功 | 22.03 秒 | `null` | 无 |

第一例提案包含 `expected_evidence=["blood_culture_result"]`、`waiting_for=["LAB_RESULT_CREATED"]`、`priority=HIGH`，证据复核节点保留了已存在的事件 ID。第二例最终提案的 `intent_type=null`，`expected_evidence`、`waiting_for`、`evidence_refs` 均为空数组。两例的平台知识检索和模型节点均显示成功。

试运行后刷新平台“套餐用量”：Agent CU 仍为 `0/20`，MaaS 免费用量从本轮前约 `4,410/2,000,000 Tokens` 增至约 `1.07 万/2,000,000 Tokens`；页面以万为单位显示后值，因此增量只是近似值。评测实验免费次数显示 `0/0`。本轮没有创建评估任务、MaaS 密钥或部署运行时。评估任务表单显示按 CU 与 Token 用量计费，不能据此假设当前账号有免费批量评估次数。

这两例只能证明平台开发环境对一例阳性和一例阴性输入给出符合预期的**候选意图**。它们没有经过已发布 AgentArts API、ClinLoop Worker 的完整事件序列、检验项目匹配、证据持久化或医生审核，因此不能纳入 `TP/FN/FP/TN` 的完整 50 例报告，也不能计算可信的 95% 召回率或证明节省人工时间。正式门槛和人工计时要求仍见 [evaluation-protocol.md](evaluation-protocol.md)。
