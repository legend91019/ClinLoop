# DeepSeek Agent 本地试用

这条路径使用合成病例 `P-1001`，把 API、Redis、Worker、DeepSeek 和医生工作台串起来。
不要把真实患者信息或 API Key 写进仓库，也不要把 Key 发到聊天中。

## 1. 准备本地环境

在仓库根目录执行：

```powershell
Copy-Item .env.example .env
```

编辑 `.env`，填入本地配置：

```dotenv
DATABASE_URL=postgresql+psycopg://clinloop:clinloop@localhost:5432/clinloop
REDIS_URL=redis://localhost:6379/0
EVENT_BUS=redis
AGENT_PROVIDER=deepseek
DEEPSEEK_API_KEY=你的本地Key
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat
```

DeepSeek 失败时，Agent 会停止当前运行并记录安全错误码，不会自动切回规则模式，也不会提交新的 Finding 或状态变化。
`.env` 保留在本机，不要把 Key 提交到 Git 或发到聊天。更新旧数据库时必须执行本节的 `alembic upgrade head`，以创建事件待发布表。

## 2. 启动服务

```powershell
docker compose up -d postgres redis
uv sync --group dev
alembic upgrade head
python -m packages.fixtures.seed
```

终端一：

```powershell
$env:DATABASE_URL="postgresql+psycopg://clinloop:clinloop@localhost:5432/clinloop"
$env:REDIS_URL="redis://localhost:6379/0"
$env:EVENT_BUS="redis"
$env:AGENT_PROVIDER="deepseek"
uv run uvicorn apps.api.app.main:app --host 127.0.0.1 --port 8000
```

终端二：

```powershell
$env:DATABASE_URL="postgresql+psycopg://clinloop:clinloop@localhost:5432/clinloop"
$env:REDIS_URL="redis://localhost:6379/0"
$env:EVENT_BUS="redis"
$env:AGENT_PROVIDER="deepseek"
uv run python scripts/run_worker.py
```

终端三：

```powershell
$env:VITE_API_BASE_URL="http://127.0.0.1:8000"
npm --prefix apps/web run dev -- --host 127.0.0.1
```

打开：

- Swagger：http://127.0.0.1:8000/docs
- 医生工作台：http://127.0.0.1:5173/?patient=P-1001

## 3. 在页面体验完整链路

打开 `http://127.0.0.1:5173/?patient=P-1001`。在 **试用 Agent 事件链** 中：

1. 点 **发送合成查房事件**。API 返回“已接收”后，等 Worker 处理，再刷新页面。**Agent 运行轨迹** 默认显示该患者全部运行；检查最新运行的模型、提案、工具调用和错误码，并在 **未闭环任务** 中确认新增等待检验的 Loop。
2. 点 **发送合成检验结果**，等 Worker 处理并刷新。新运行应关联刚建的 Loop，出现 `get_labs` 与 `get_progress_notes` 工具记录。若结果匹配、尚无明确医生确认，**流程缺口**会出现待审核的结果响应 Finding。医生可打开证据并接受或驳回。

请先等第一条事件处理完成，再发第二条；连续创建多条相同的查房任务会使检验与任务的关联不唯一，Agent 会保守地停止告警。页面中的“已接收”只表示事件入库，Worker 处理与 DeepSeek 调用是异步的。这个入口只发送固定合成数据，不接受自由输入或真实病历。

也可在 Swagger 的 `POST /api/v1/events` 手动提交相同结构的合成事件。每条事件使用新的 `event_id` 与当前时间；旧时间会按历史事件处理，不一定能关联新任务。Worker 完成后，在运行轨迹中检查 `deepseek · deepseek-chat`、提案引用、模型摘要和停止原因。模型只产生候选意图和计划，Guard 与医生审核仍控制高风险工作流变化。

API 会把事件与待发布记录一起提交。如果 Redis 暂时不可用，Worker 恢复后会补发待发布事件；Redis 已投递而 Worker 中断的 pending 消息也会被重新领取。重复投递按事件 ID 幂等处理。请保持 Worker 运行，以免事件一直停留在待处理状态。

当前在线 Worker 的确定性缺口核对只覆盖**已关联检验结果 → 医生响应**。工具调用能证明检索动作和来源范围，但模型/工具结果仍需医生审核。本流程是工程演示，不是临床效率或安全性验证；其他缺口类别、真实 EHR 接口、多患者队列和线上 DeepSeek 的质量评估仍待完成。

## 4. 不使用 Docker 的离线模式

如果 Docker Desktop 未启动，仍可使用 `sqlite + mock` 运行既有演示：

```powershell
$env:DATABASE_URL="sqlite+pysqlite:///demo.sqlite3"
uv run python scripts/run_demo.py --patient P-1001 --database-url sqlite+pysqlite:///demo.sqlite3 --no-review
```

这个模式验证工作流和 UI，但不会调用 DeepSeek，也不会提供 API → Redis → Worker 的真实链路。
