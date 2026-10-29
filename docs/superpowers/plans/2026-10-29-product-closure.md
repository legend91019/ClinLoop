# ClinLoop 本地产品收口实施计划

> **供 Coding Agent 执行：** 按任务逐项完成，先写测试，再改实现。

**目标：** 让合成患者工作台成为可重复启动的本地产品入口。

**架构：** 复用现有示例数据函数和 API；只调整默认导航、本地初始化及说明。保留深链接和旧版事件链。可观测性与云部署不在本计划范围。

**技术栈：** Python、FastAPI、SQLAlchemy、React、Vitest、pytest。

## 全局约束

- 仅使用合成数据。
- 自动验收不调用付费模型 API。
- 医生审核仍是创建任务与临床闭环的前置条件。

## 任务 1：默认产品入口

**文件：** `apps/web/src/navigation.ts`、`apps/web/src/App.navigation.test.tsx`

- [x] 添加 `/` 打开患者列表的测试，同时保留指定患者深链接。
- [x] 修改默认页面，重跑导航测试。

## 任务 2：统一本地初始化

**文件：** `scripts/init_product_demo.py`、`tests/integration/test_product_demo_init.py`

- [x] 对临时 SQLite 库测试首次及重复初始化。
- [x] 复用 `init_local_trial` 与 `seed_workspace_patients`。
- [x] 运行集成测试及后端测试集。

## 任务 3：统一本地说明

**文件：** `README.md`、`docs/development/patient-workspace.md`、`docs/development/patient-agent-handoff.md`

- [x] 将快速启动收为同一数据库、三个终端。
- [x] 区分 mock、DeepSeek 和旧版 `P-1001` 演示。
- [x] 核对命令并运行发布检查。

## 任务 4：最终本地验证

- [x] 运行后端 pytest 和 Ruff。
- [x] 运行前端测试、lint、格式检查及构建。
- [x] 核对改动不包含云部署或可观测性实现。
