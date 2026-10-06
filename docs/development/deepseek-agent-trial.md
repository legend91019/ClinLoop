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

## 3. 发送一条事件

在 Swagger 的 `POST /api/v1/events` 中提交合成事件：

```json
{
  "event_id": "EVT-DEEPSEEK-001",
  "patient_id": "P-1001",
  "encounter_id": "ENC-2001",
  "event_type": "NOTE_CREATED",
  "event_time": "2026-10-06T10:00:00+08:00",
  "source_time": "2026-10-06T10:00:00+08:00",
  "payload_ref": "NOTE-DEEPSEEK-001",
  "actor": {
    "actor_id": "DR-TEST",
    "role": "PHYSICIAN",
    "display_name": "试用医生"
  },
  "payload": {
    "text": "复查血培养，结果出来后再决定下一步"
  }
}
```

Worker 完成后，打开工作台的 **Agent 运行轨迹**，应看到 `deepseek · deepseek-chat`、提案引用、模型摘要和运行停止原因。模型只产生候选意图和计划，Guard 与医生审核仍控制高风险工作流变化。

## 4. 不使用 Docker 的离线模式

如果 Docker Desktop 未启动，仍可使用 `sqlite + mock` 运行既有演示：

```powershell
$env:DATABASE_URL="sqlite+pysqlite:///demo.sqlite3"
uv run python scripts/run_demo.py --patient P-1001 --database-url sqlite+pysqlite:///demo.sqlite3 --no-review
```

这个模式验证工作流和 UI，但不会调用 DeepSeek，也不会提供 API → Redis → Worker 的真实链路。
