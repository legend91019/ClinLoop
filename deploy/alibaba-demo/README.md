# ClinLoop 阿里云 Demo 部署

本目录提供一套单机 Docker Compose 部署，适合比赛演示和合成数据联调。默认使用 mock Agent，不需要充值或配置大模型 API。

## 1. 服务器准备

- Ubuntu 22.04+
- Docker 24+
- Docker Compose v2+
- 建议可用磁盘至少 10 GB

在阿里云 ECS 安全组放行：

- `TCP 80`：公网访问 Web 页面
- `TCP 22`：仅保留你的管理 IP

如果暂时不想开放 80，可使用下面的 SSH 隧道，仅自己访问。

## 2. 部署

```bash
git clone https://github.com/legend91019/ClinLoop.git
cd ClinLoop/deploy/alibaba-demo
cp .env.example .env
mkdir -p data
chmod 700 data
docker compose build --pull
docker compose up -d
docker compose ps
```

首次启动会自动初始化 P-1001 与 P-2001～P-2006 合成患者。SQLite 文件保存在 `data/clinloop-demo.sqlite3`。

## 3. 验证

```bash
curl http://127.0.0.1/healthz
curl http://127.0.0.1/readyz
curl http://127.0.0.1/api/v1/patients
docker compose logs --tail=100 api worker web
```

浏览器访问：`http://服务器公网IP/`。

## 4. 不开放公网 80 时的访问

在本地电脑建立隧道：

```bash
ssh -N -L 18080:127.0.0.1:80 root@服务器公网IP
```

再打开 `http://127.0.0.1:18080/`。隧道关闭后不会影响服务器容器。

## 5. 切换真实模型或 AgentArts

默认配置：

```dotenv
AGENT_PROVIDER=mock
NOTE_DRAFT_PROVIDER=mock
```

正式接入前，先在 `.env` 中按项目文档填入 AgentArts API 地址、工作流 ID 和密钥，再重启：

```bash
docker compose up -d --force-recreate api worker web
```

不要把 `.env`、API Key 或服务器登录文件提交到 Git。生产环境必须增加认证、HTTPS、数据库备份和日志/指标采集。

## 6. 停止与更新

```bash
docker compose down
git pull --ff-only origin main
docker compose build --pull
docker compose up -d
```
