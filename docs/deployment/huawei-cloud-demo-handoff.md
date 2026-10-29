# 华为云 ECS 演示与可观测交接手册

> 面向负责云端部署的队友。以仓库 `main` 的实际代码为准；本文写于 2026-10-29。**只使用仓库生成的合成患者，不上传真实病例。** 队长此前要求暂不充值：任何 ECS、EIP、云盘、MaaS、LTS 等资源创建前，先在控制台核对免费权益、代金券适用范围和预计费用；不在已获额度内就先停在本地/现有资源演示。

## 交付目标和现状

| 层次 | 队友完成后应看到 | 不能据此声称 |
| --- | --- | --- |
| A. 云端产品 | 浏览器打开患者目录，`P-2001` 等六位合成患者可刷新、可保存；API、数据库、Worker 在 ECS 上实际运行 | 真实模型有效、临床节时 |
| B. 可观测 | API 就绪检查、Worker 状态、待处理事件数、运行轨迹、ECS 资源指标和可检索日志有截图 | 已达到临床级可用性 |
| C. 真实 Agent | 已发布 AgentArts 运行时被 Worker 调用，运行轨迹明确显示 `agentarts`，只读工具、Guard、医生审核可追溯 | 只凭一条成功轨迹声称 95% 召回 |
| D. 固定评测 | 已发布运行时完成冻结的 50 例合成病例评测，原始 JSON、命令、版本和失败病例均保留 | 用 mock/rules/画布两例冒充平台评测；用合成评测冒充实际节时 |

当前 `main` 已有 A 所需代码、合成数据初始化、数据库 Outbox、后台 Worker、页面和测评脚本。AgentArts 画布曾免费试运行两例，但**尚无已发布运行时的 50 例报告**。本手册指导队友完成部署和取证，不预设华为云余额或已购买资源。

## 0. 先核对账户与费用

1. 进入华为云中国站，确认与 AgentArts 一致的账号及区域（现有画布记录为 `cn-southwest-2`，西南-贵阳一）。查看可用免费权益、优惠券/代金券、余额、过期日及 ECS/EIP/云盘的结算方式。**AgentArts 免费试运行额度不等于部署后 MaaS 调用、ECS 和 LTS 免费。** [AgentArts 计费项](https://support.huaweicloud.com/price-agentarts/agentarts_08_0003.html)。
2. 先用已有 ECS；若新购，建议从 Ubuntu 24.04、2 vCPU/4 GiB、约 40 GiB 系统盘作为短时演示的**起始估算**，实际规格以构建、运行负载和控制台报价为准。短时展示可先不买 RDS、Redis、ELB、LTS；本方案用单机 SQLite 和单 Worker。参考[华为云 ECS 快速入门](https://support.huaweicloud.com/qs-ecs/ecs_01_0103.html)。
3. 若没有已覆盖费用的额度，先不要开通可计费运行时或日志服务。队友把控制台费用预估截图交队长判断。不要把账号密码、访问密钥、API Key 发到群聊或提交到 Git。

## 1. 架构与网络边界

```mermaid
flowchart LR
    B[浏览器] -->|SSH 隧道 / HTTPS| N[Nginx 静态页与反向代理]
    N -->|127.0.0.1:8000| A[FastAPI]
    A <--> D[(单机 SQLite 合成病例)]
    D -->|事务 Outbox| W[单个 Worker]
    W -->|mock / 已发布 AgentArts| M[Agent Provider]
    W --> G[只读工具 + Guard]
    A -.本机检查.-> H[/healthz + /readyz]
    A -.日志.-> L[LTS 可选]
    W -.日志.-> L
    E[ECS] -.CPU/内存/磁盘.-> C[CES]
```

`docker-compose.yml` 是本地开发配置：数据库密码写死、数据库/Redis 端口对宿主机开放、源码挂载、`worker` 为一次性演示任务，且没有前端服务。**不要直接把它作为公开云端部署。** 本手册采用单台 ECS、`systemd` 和 Nginx；SQLite 只适合短时合成数据演示，且只能启动**一个** Worker。若要长期开放、多 Worker 或真实业务，再独立设计 PostgreSQL、备份、身份认证和并发控制。

安全组只放行团队来源 IP 的 TCP 22。私下预览采用 SSH 隧道，无需开放 80/443；公开演示才放行 443 并配置域名、TLS、可信身份网关。不要对公网开放 8000、5432、6379。规则操作见[华为云安全组文档](https://support.huaweicloud.com/usermanual-vpc/zh-cn_topic_0030969470.html)。当前应用里的 `X-Actor-Id`/`X-Actor-Role` 只是演示标识，**不能当作公网登录认证**；未经身份网关保护，不要公布页面或业务 API。AgentArts HTTP 工具路径由单独的 `X-ClinLoop-Tool-Key` 校验，详见[平台工作流手册](../agentarts/workflow-runbook.md)。

## 2. ECS 上安装和初始化（Ubuntu 24.04，`ubuntu` 用户）

以下在 ECS 的 SSH 终端执行。若使用不同用户名或路径，须同步修改数据库 URL、`systemd` 单元路径和日志采集路径。示例命令仅做短时私有演示。先按[uv 官方安装说明](https://docs.astral.sh/uv/getting-started/installation/)安装 `uv` 并确认 `uv --version`；`git`、`nginx`、`sqlite3` 可从 Ubuntu 软件包安装。Python 要求 3.12+。前端建议由队友在已有 Node.js 22+ 的电脑构建后上传，避免在 ECS 上另装 Node。

```bash
sudo apt update
sudo apt install -y git nginx sqlite3 python3.12 python3.12-venv
git clone https://github.com/legend91019/ClinLoop.git /home/ubuntu/ClinLoop
cd /home/ubuntu/ClinLoop
git checkout main
git pull --ff-only
git rev-parse HEAD                 # 记录演示版本
uv sync --python python3.12
mkdir -p data logs
chmod 700 data logs
```

在仓库根目录创建 **不入 Git** 的 `.env`。单机路径应为四个斜杠开头的绝对 SQLite URL。第一次先运行 mock，确认整条业务链可用；真实模型切换在第 6 节。

```bash
cat > .env <<'EOF'
DATABASE_URL=sqlite+pysqlite:////home/ubuntu/ClinLoop/data/clinloop-demo.sqlite3
EVENT_BUS=database
AGENT_PROVIDER=mock
NOTE_DRAFT_PROVIDER=deepseek
EOF
chmod 600 .env
uv run python -m scripts.init_product_demo
uv run python -m scripts.init_product_demo  # 幂等复核，不应重复添加六位患者
```

预期打印 `P-1001 plus six patient workspaces`，第二次 `0 added`。`P-2001` 至 `P-2006` 是合成患者；初始化不会清空已有数据。`.env` 和 `data/` 不得上传仓库或分享群。

## 3. API 与 Worker 守护进程

创建两个单元。`EnvironmentFile` 让 API、Worker 指向同一个数据库；`WorkingDirectory` 保证相对路径与本地开发一致。`systemd` 将标准输出写到指定文件，供本机检查或 LTS 采集。

```bash
sudo tee /etc/systemd/system/clinloop-api.service >/dev/null <<'EOF'
[Unit]
Description=ClinLoop API
After=network-online.target
Wants=network-online.target
[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/ClinLoop
EnvironmentFile=/home/ubuntu/ClinLoop/.env
ExecStart=/home/ubuntu/ClinLoop/.venv/bin/uvicorn apps.api.app.main:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=3
StandardOutput=append:/home/ubuntu/ClinLoop/logs/api.log
StandardError=append:/home/ubuntu/ClinLoop/logs/api.log
[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/clinloop-worker.service >/dev/null <<'EOF'
[Unit]
Description=ClinLoop single Worker
After=network-online.target clinloop-api.service
Wants=network-online.target
[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/ClinLoop
EnvironmentFile=/home/ubuntu/ClinLoop/.env
ExecStart=/home/ubuntu/ClinLoop/.venv/bin/python -m scripts.run_worker
Restart=on-failure
RestartSec=3
StandardOutput=append:/home/ubuntu/ClinLoop/logs/worker.log
StandardError=append:/home/ubuntu/ClinLoop/logs/worker.log
[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now clinloop-api clinloop-worker
systemctl --no-pager --full status clinloop-api clinloop-worker
curl -fsS http://127.0.0.1:8000/healthz
curl -fsS http://127.0.0.1:8000/readyz
```

`/healthz` 表示进程响应，`/readyz` 会查询数据库。若失败，先查看 `systemctl status` 和 `tail -n 100 logs/api.log logs/worker.log`，再核对 `.env` 和数据库文件权限。不要在截图中展示密钥、原始病例文本或完整模型请求。

## 4. 构建页面、Nginx 和私有预览

在队友自己的开发机，从同一 `main` 提交构建前端。`VITE_API_BASE_URL` 设为空字符串，构建后的浏览器只访问当前页面域名下的 `/api/v1`，由 Nginx 代理；不需要在源码里写 ECS 公网 IP。PowerShell 示例：

```powershell
git checkout main
git pull --ff-only
npm --prefix apps/web ci
$env:VITE_API_BASE_URL = ""
npm --prefix apps/web run build
scp -r apps/web/dist ubuntu@YOUR_EIP:/home/ubuntu/ClinLoop/web-dist
```

`scp` 使用团队自己的 SSH 密钥；如无 EIP，可通过云控制台文件传输或堡垒机上传。ECS 上将构建产物放到 Nginx 可读目录：

```bash
sudo mkdir -p /var/www/clinloop
sudo cp -a /home/ubuntu/ClinLoop/web-dist/. /var/www/clinloop/
sudo chown -R www-data:www-data /var/www/clinloop
sudo tee /etc/nginx/sites-available/clinloop >/dev/null <<'EOF'
server {
    listen 127.0.0.1:8080;
    server_name _;
    root /var/www/clinloop;
    index index.html;

    location /api/v1/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Real-IP $remote_addr;
    }
    location / {
        try_files $uri $uri/ /index.html;
    }
}
EOF
sudo ln -s /etc/nginx/sites-available/clinloop /etc/nginx/sites-enabled/clinloop
sudo nginx -t
sudo systemctl reload nginx
curl -I http://127.0.0.1:8080/
curl -fsS http://127.0.0.1:8080/api/v1/patients
```

若默认 Nginx 站点仍启用，不影响本方案的 `127.0.0.1:8080`。在队长电脑开 SSH 隧道，再浏览 `http://127.0.0.1:8080/`：

```powershell
ssh -L 8080:127.0.0.1:8080 ubuntu@YOUR_EIP
```

把 `YOUR_EIP` 换成 ECS 的真实 EIP。如果本机 8080 已占用，改用 `ssh -L 18080:127.0.0.1:8080 ...` 并打开 `http://127.0.0.1:18080/`。语音转录需要浏览器权限和安全上下文；私有预览先用粘贴文本，正式 HTTPS 再检查麦克风。**公网赛事链接**由队友另配域名/TLS 和可信身份网关，先验证费用与访问控制，再开放安全组 443；业务 API 仍仅监听 127.0.0.1。没有网关时，保持 SSH 隧道私有演示。

## 5. 一条真正经过数据库和 Worker 的演示

1. 打开 `/`，看到患者列表；选择 `P-2001`。刷新页面后患者仍存在，说明不是前端写死列表。
2. 进入“病历与查房”，填写合成医生身份，录入带角色标识的**合成**问诊/查房文字，例如 `医生：血培养结果出来后请提醒我查看。患者：目前仍有发热。`。选“文书格式演示（本地模板）”，保存原文，检查原文与文书记录可刷新保留。
3. 审核并签署文书。进入“患者 Agent 助手”，查看候选任务及其原文依据，手动确认；待办应出现。发送页面提供的模拟检验结果，等待 Worker 运行；进入“运行轨迹”和“原始证据”，核对同一患者、事件来源和停止原因。
4. 由医生查看结果、填写处理说明、确认闭环，再打开“交班草稿”确认仍未完成的高优先级事项是否被带入。精确按钮名和状态见[患者工作台说明](../development/patient-workspace.md)及[患者 Agent 接手说明](../development/patient-agent-handoff.md)。

**本节默认 `mock`，只证明产品交互、持久化、Worker、审核与证据链可运行；不能声称真实 Agent 推理。** 把浏览器页面、`P-2001` 数据、运行轨迹与下节的进程/队列截图放在同一个演示记录里，标明提交 SHA 和模式。

## 6. 可观测：先本机，费用允许再上云

### 最小观测（无需 LTS）

```bash
systemctl is-active clinloop-api clinloop-worker
curl -fsS http://127.0.0.1:8000/readyz
tail -n 50 /home/ubuntu/ClinLoop/logs/api.log
tail -n 50 /home/ubuntu/ClinLoop/logs/worker.log
sqlite3 /home/ubuntu/ClinLoop/data/clinloop-demo.sqlite3 \
  'SELECT COUNT(*) AS pending_outbox FROM event_publications WHERE published_at IS NULL;'
sqlite3 /home/ubuntu/ClinLoop/data/clinloop-demo.sqlite3 \
  'SELECT run_id, trigger_event_id, stop_reason, started_at, finished_at FROM agent_runs ORDER BY started_at DESC LIMIT 5;'
```

演示提交事件后，`agent_runs` 应出现新的运行；`pending_outbox` 应回落。不要把“队列为 0”单独当成成功证据，也要看这次事件的轨迹、候选、来源和医生决策。若日志包含合成患者原文，取证时截取必要字段并遮盖内容。

### 云监控 CES 与云日志 LTS（可选）

- ECS 控制台或 CES 查看 CPU、内存、磁盘和网络图，并给 CPU 高、磁盘空间低、实例异常配置告警；内存/磁盘指标可能需要 Agent，按控制台实际能力操作。[CES 应用场景](https://support.huaweicloud.com/productdesc-ces/ces_07_0003.html)。
- 只有在队长确认**当前额度覆盖费用**后，按[华为云 ECS 文本日志接入 LTS](https://support.huaweicloud.com/usermanual-lts/lts_04_1031.html)安装 ICAgent，创建 `clinloop-demo` 日志组，以及 `api`、`worker` 两条日志流；采集路径分别为 `/home/ubuntu/ClinLoop/logs/api.log` 和 `.../worker.log`，短保留期，检查索引及采集开关。Nginx 访问日志可加第三条流，但先核对日志内容。不要采集 `.env`、数据库、模型请求体或病历原文；LTS 的存储和分析可能计费。
- 演示结束记录 LTS 查询页的时间、服务、错误码与 ECS 指标截图。费用不允许时，本机 `systemd`/SQL/日志证据已足以证明演示过程可观测，报告中注明没有 LTS。

## 7. 已发布 AgentArts 运行时与固定测评（额外费用门槛）

已有 AgentArts 工作流在 `cn-southwest-2`，工作流和知识库编号见[平台工作流手册](../agentarts/workflow-runbook.md)。先在画布确认知识检索、意图提案、证据复核及输出契约，按[官方发布部署步骤](https://support.huaweicloud.com/lowcode-agentarts/agentarts_05_0053.html)提交版本并部署；**部署前必须核对 MaaS、运行时和 LTS/AOM/APM 费用与余额，不要把免费试运行当成发布后免费。** 如无已覆盖额度，停在试运行并如实标注。

若额度明确覆盖，运行时名称、基础 URL 和密钥只放 ECS 的 `.env`，并重启 Worker。`AGENTARTS_ENDPOINT` 是基础 URL，不是完整调用路径；按控制台实际“调用路径”拆分。API 侧工具回调需要 `AGENTARTS_TOOL_KEY`；只有为工具提供**可信 HTTPS 地址与隔离的密钥认证**后才在画布启用 HTTP 工具节点。Nginx 私有 SSH 端口不能被 AgentArts 云端调用。按[平台工作流手册](../agentarts/workflow-runbook.md)完成节点映射和回调路径检查。

```bash
# 这些是 .env 中要填写的键名，值从华为云控制台安全获取；不要复制示例占位符运行。
AGENT_PROVIDER=agentarts
AGENTARTS_ENDPOINT=https://<控制台给出的基础地址>
AGENTARTS_RUNTIME_NAME=<控制台给出的运行时名称>
AGENTARTS_API_KEY=<安全保存的密钥>
AGENTARTS_TOOL_KEY=<独立生成的工具回调密钥>
```

```bash
chmod 600 /home/ubuntu/ClinLoop/.env
sudo systemctl restart clinloop-api clinloop-worker
systemctl --no-pager --full status clinloop-api clinloop-worker
```

先用一例阳性、一例阴性手动试运行，核对 Worker 轨迹中的 `agentarts`、真实运行时名称、工具调用和 Guard 结果。再运行六例烟测。**只有调用已发布运行时且费用额度允许**，才运行冻结的 50 例：

```bash
cd /home/ubuntu/ClinLoop
uv run --env-file .env python -m eval.run_online_eval --provider agentarts --corpus smoke-v1 \
  --output artifacts/eval/agentarts-smoke-local.json
uv run --env-file .env python -m eval.run_online_eval --provider agentarts --corpus contest-v1 \
  --assert-contest-target --output artifacts/eval/agentarts-online-local.json
```

冻结集 25 阳性、25 阴性；预登记门槛为召回率 ≥95%、精确率 ≥90%、阴性误报率 ≤10%、证据有效率 100%、模型错误 0。由于阳性只有 25 条，至少检出 24 条才实际达到 96% 召回；23 条为 92%，不达标。命令退出非零时仍保存报告，**不得删掉失败病例或修改分母**。对照基线规则为 TP19/FN6/FP0/TN25（召回 76%），是合成工程基线，不是临床效果。细则与限制见[评测协议](../agentarts/evaluation-protocol.md)和[评测说明](../../eval/README.md)。人工节时必须有真实参与者的成对计时；当前没有，不能写“实际节省 X% 医生时间”。

## 8. 队友交付给队长的材料

在 PR 或交接文档中填下表；**不要提交密钥、`.env`、SQLite 文件、日志全文或 `artifacts/` 原始文件到公开仓库**。评测 JSON 可经脱敏检查后放受控共享目录，公开 README 只放汇总表、实验条件与可复核命令。

| 交付项 | 必填内容 |
| --- | --- |
| 版本与环境 | Git SHA、区域、ECS 系统与规格、部署时间、URL/SSH 隧道方式、配置键名（无值） |
| 费用 | 免费额度/代金券截图、已发生费用、哪些功能未启用及原因 |
| 产品演示 | 患者列表、文书、候选任务、检验结果、证据、医生确认、交班的短视频或带时间戳截图 |
| 后台证据 | `/readyz`、API/Worker `active`、Outbox 前后计数、`agent_runs` 新记录；日志只给必要片段 |
| AgentArts | 画布版本、运行时名称、真实轨迹和工具回调截图；若未部署，明确写“仅画布试运行” |
| 评测 | 命令、语料版本、TP/FP/FN/TN、召回/精确/误报、证据有效性、模型错误、失败病例、原始报告保存位置 |
| 收尾 | 演示窗口结束后停止/释放资源及费用核对截图；保留需要复现实验的配置说明（无密钥） |

更新代码时执行 `git pull --ff-only`，按新 SHA 重建前端、`uv sync`、重启两个服务、重新跑健康检查。数据库迁移版本变更时，先备份合成数据库并检查迁移说明；不要通过重新初始化覆盖已录入的演示过程。若需公开赛事 Demo，而当前仍只有演示身份头，请先补可信身份网关和 HTTPS，再开放访问。
