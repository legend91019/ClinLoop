# DeepSeek Agent 本地试用

使用全新的合成病例数据库体验 `API → Worker → DeepSeek → Guard → 医生审核 → 交班草稿`。只发送固定合成事件；不要输入真实患者资料。DeepSeek 密钥只需放在 Worker 终端的环境变量中，不写入仓库或 `.env`。

## 不使用 Docker：SQLite + 数据库 Worker

以下命令都在仓库根目录执行。先安装依赖，并创建一份**专用的新数据库**：

```powershell
uv sync --group dev
npm --prefix apps/web ci
$env:DATABASE_URL="sqlite+pysqlite:///clinloop-local.sqlite3"
uv run python scripts/init_local_trial.py
```

`init_local_trial.py` 只创建合成患者 `P-1001`、就诊 `ENC-2001` 和空表，不预填演示任务。重复运行不会清空数据；想从头体验时，改用另一个尚不存在的 SQLite 文件名，并在三个终端保持同一 `DATABASE_URL`。

打开三个 PowerShell 终端，每个终端都进入仓库根目录。

**终端一：API**

```powershell
$env:DATABASE_URL="sqlite+pysqlite:///clinloop-local.sqlite3"
$env:EVENT_BUS="database"
uv run uvicorn apps.api.app.main:app --host 127.0.0.1 --port 8000
```

**终端二：真实 DeepSeek Worker**

```powershell
$env:DATABASE_URL="sqlite+pysqlite:///clinloop-local.sqlite3"
$env:EVENT_BUS="database"
$env:AGENT_PROVIDER="deepseek"
$env:DEEPSEEK_MODEL="deepseek-flash"
$env:DEEPSEEK_API_KEY = Read-Host "DeepSeek API Key" -AsSecureString | ConvertFrom-SecureString -AsPlainText
uv run python scripts/run_worker.py
```

PowerShell 会在输入密钥时隐藏字符。请使用新密钥；曾在聊天中发出的密钥应在 DeepSeek 控制台撤销并更换。不要把含密钥的终端输出、环境快照或数据库提交到 Git。

**终端三：医生工作台**

```powershell
$env:VITE_API_BASE_URL="http://127.0.0.1:8000"
npm --prefix apps/web run dev -- --host 127.0.0.1
```

打开 [工作台](http://127.0.0.1:5173/?patient=P-1001)。项目要求 Python 3.12+。

## 页面上按顺序体验

在 **试用 Agent 事件链** 中按顺序发送事件。页面会查询这次事件对应的运行；Worker 处理完成后自动刷新时间线、任务、缺口和轨迹。处理期间按钮会暂时禁用，避免连续提交造成关联歧义。等待超过 45 秒或状态查询失败时，页面会保留事件 ID 并锁住下一步；检查 Worker 后点击 **重新查询 Agent 状态**，无需再次发送事件。若发送响应丢失，可先查询状态，再用 **重试发送同一事件** 沿用原事件 ID；已入库的事件会返回冲突，不会被再次创建。试用状态保存在当前浏览器会话中，刷新页面或切换患者后返回仍可继续。顶部的手动刷新按钮可查看最新患者数据，但不会跳过事件状态确认。开始新数据库试用时请用新的浏览器会话：

1. **查房事件**：DeepSeek 解析随访意图，Agent 创建等待血培养的 Loop。
2. **血培养结果**：Agent 调用只读 `get_labs` / `get_progress_notes`，Guard 核对来源与关联，把 Loop 推进到 `RESULT_AVAILABLE`，显示待医生审核的 Finding。点缺口中的证据可以查看源事件。
3. **医生确认**：合成医生记录明确引用上一步的检验事件；原 Loop 变成 `ACKNOWLEDGED`，生成等待药敏的依赖 Loop。
4. **药敏结果**：新结果关联依赖 Loop，并产生新的待审核 Finding。

在 **Agent 运行轨迹** 中检查 `deepseek · deepseek-flash`、前次运行引用、只读工具、停止原因。页面显示“事件已接收”仅代表 API 已入库；只有出现“Agent 已处理”才表示对应运行已持久化。若显示模型错误，核对 Worker 和轨迹后再处理，不要直接重复发送相同随访任务；重复任务会造成结果关联歧义，Agent 会保守停止告警。

填写就诊 ID `ENC-2001` 和合成医生身份后，可在 **交接草稿** 手动创建草稿。草稿应带入尚未关闭的高优先级任务、已核实证据和待审核缺口；存在待审核 Finding 时不得封存。医生接受或驳回 Finding 会追加审计记录。

API 文档在 [Swagger](http://127.0.0.1:8000/docs)。数据库 Worker 逐个消费 API 的事务性 outbox；停止 Worker 后新事件会留待下次启动处理。此模式只适合本机单 Worker 试用。

## Docker / Redis 模式

已有 PostgreSQL 和 Redis 时，仍可按仓库的 Docker 配置运行。设置 `EVENT_BUS=redis`、PostgreSQL `DATABASE_URL`、`REDIS_URL`，执行 `alembic upgrade head`，分别启动 API、`scripts/run_worker.py` 和前端。Redis 模式支持 pending 消息恢复。若要体验**空病例的在线流程**，不要运行预填全套 Loop/Finding 的 `packages.fixtures.seed`；它用于固定演示与评测。

## 范围

这条在线路径已验证检验结果与医生确认的连续性、依赖任务和交班草稿。其他缺口类别仍主要在合成演示和离线评测中；真实 EHR、身份认证、多 Worker 并发与临床效率评估尚未完成。所有结果仅证明工程链路运行，不能作为临床有效性结论。
