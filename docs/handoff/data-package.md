# ClinLoop 合成数据包 v1

本压缩包来自 ClinLoop 仓库的固定合成数据生成器和已提交测评报告。**没有真实患者数据、API 密钥、云端运行时响应或人工实验记录**。它供队友离线复现、联调和制作比赛材料，不代表临床有效性。

## 文件与用途

| 文件 | 内容 | 使用方式 |
| --- | --- | --- |
| `data/contest-v1-inputs.jsonl` | 固定 50 例；每行一个 `case_id`、`patient_id` 和按顺序排列的 `events` | 输入数据；不要把标签并入 Agent 提示词或知识库。 |
| `labels/contest-v1-labels.csv` | 50 例的 `cohort`、`expected_alert` | 仅评分端读取；25 阳性、25 阴性。 |
| `data/smoke-v1-inputs.jsonl`、`labels/smoke-v1-labels.csv` | 6 例快速回归的输入和答案 | 先联调，再跑固定 50 例。 |
| `reports/contest-rules-report.json` | 50 例规则基线：TP 19、FN 6、FP 0、TN 25 | 仅与同一数据集的 AgentArts 完整 Worker 结果比较。 |
| `reports/online-report.json` | 6 例规则与确定性 MOCK 回归结果 | MOCK 不是 LLM。 |
| `reports/offline-report.json`、`reports/comparison.csv` | 100 条合成轨迹离线回放 | 验证数据契约与流程指标；不当作在线 Agent 效果。 |
| `knowledge/knowledge-sop-v1.md` | 工作流 SOP 知识文本 | 仅上传此知识文本；不要上传标签或测评报告。 |
| `manifest.json` | 样本数、语料 SHA-256、包内文件 SHA-256 | 检查版本与文件完整性。 |

`contest-v1` 的语料 SHA-256 是 `b8780d14be703102e22c196706308a279e030ca2a4eb24d73d21b507f21dcd90`。计算方式与仓库 `eval.run_online_eval` 一致：按 `case_id` 顺序序列化包含 `case_id`、`cohort`、`expected_alert`、`events` 的数组，JSON 键排序，保留中文字符，再求 SHA-256。输入 JSONL 故意不含答案；这个语料哈希只用于版本核对。

## 读取示例

在仓库根目录解压后，可用 Python 标准库读取：

```python
import csv
import json
from pathlib import Path

root = Path("解压后的目录")
inputs = [
    json.loads(line) for line in (root / "data/contest-v1-inputs.jsonl").open(encoding="utf-8")
]
with (root / "labels/contest-v1-labels.csv").open(encoding="utf-8", newline="") as stream:
    labels = {row["case_id"]: row for row in csv.DictReader(stream)}
assert len(inputs) == len(labels) == 50
```

`events` 是 `ClinicalEvent` 的 JSON 形式，契约定义在仓库 `packages/contracts/models.py`。评分时按 `case_id` 关联标签，不根据输入文本临时改标签。每例事件应在新的数据库中重放；仓库的正式在线评测已经处理了数据库隔离、Worker、只读工具、Finding 和证据评分，首选直接运行它。

## 复现与边界

```powershell
uv sync --group dev
uv run python -m eval.run_online_eval --provider rules --corpus contest-v1 --output artifacts/eval/contest-rules-local.json
uv run python scripts/build_teammate_pack.py --output docs/handoff/clinloop-synthetic-data-v1.zip
```

50 例的 **95% 召回率是目标**，要求 25 阳性中至少检出 24 例；当前规则基线是 19/25，即 76%。AgentArts 目前只有两例免费画布试运行，尚无已发布运行时的 50 例完整 Worker 结果。100 条离线轨迹、确定性 MOCK 和规则结果不能称为 AgentArts 成绩。数据集只覆盖检验结果随访这一类在线告警，样本由少量模板变体构成，不支持临床泛化结论。

如需修改病例，请在 `eval/online/cases.py` 中新增版本并重新冻结标签、语料哈希和报告；不要在已公布的 `contest-v1` 上反复调参后再把它当未见测试集。原始参考资料见仓库 `docs/agentarts/evaluation-protocol.md` 和 `eval/README.md`。
