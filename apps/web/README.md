# ClinLoop 医生工作台

React 18 / TypeScript / Vite / Vitest。所有病例为合成数据，工程验证不构成临床有效性证明。

## 本地启动

在仓库根目录运行（PowerShell 可使用 `npm.cmd`）：

```powershell
npm.cmd --prefix apps/web install --workspaces=false --no-audit --no-fund
npm.cmd --prefix apps/web run dev
```

打开 `http://localhost:5173/?patient=P-1001`。默认查询最近 24 小时；历史合成病例可选择 720 小时（30 天），不改变事件时间。提供 72 小时窗口。

默认 API 地址为 `http://localhost:8000`。可在启动前设置 `VITE_API_BASE_URL`，例如：

```powershell
$env:VITE_API_BASE_URL = 'http://localhost:8001'
npm.cmd --prefix apps/web run dev
```

使用同源开发代理时，设置 `VITE_API_BASE_URL=/api`。`API_PROXY_TARGET` 默认为 `http://localhost:8000`；可单独配置代理目标。生产构建使用相对路径时，部署服务也必须代理 `/api`。跨域 API 需配置正确的 CORS 来源。

## 审核与交接

- 显式填写医生 ID，并选择 `PHYSICIAN` 或 `CLINICIAN`。写操作携带 `X-Actor-Id` / `X-Actor-Role`。这些是演示审计身份；生产认证由网关提供。
- Gap 原始 claim、支持证据和检索来源始终保留。接受仅记录审核决定。驳回需要非空理由；失败保留输入，可再次提交。
- 从 Gap 证据按钮打开原始 ClinicalEvent，查看完整 payload。来源患者必须与当前患者一致；来源引用支持事件 ID 或 payload_ref。患者自述保持独立的待核验徽标。
- 就诊 ID 由医生明确输入，或在已校验的原始证据中点击“选用此就诊 ID”。不会默认使用 `ENC-2001`，也不会替其他患者沿用就诊 ID。
- 交接保存仅发送 situation / background / assessment / recommendation。IDs、确认事实、待办与状态只读。已有报告可通过交接报告 ID 打开。
- 未保存文本、身份缺失、审核数据不可用或待审核事项都会阻止封存。封存前再次查询审核状态，后端仍是最终守卫。封存后 SBAR 文本不可编辑。
- 切换患者清空证据抽屉、就诊选择和本地草稿；读请求取消，忽略已过期响应。请求错误和空态分别展示，不把“未找到”解释成“不存在”。

## 检查

```powershell
npm.cmd --prefix apps/web run test -- --run
npm.cmd --prefix apps/web run lint
npm.cmd --prefix apps/web run format:check
npm.cmd --prefix apps/web run build
```

测试仅使用 `src/test` 内合成 fixtures，在 HTTP 边界替代外部网络。UI 测试运行真实组件、hook 和 ApiClient。

## 限制

草稿只有成功保存后才持久化；页面刷新或切换患者会丢失尚未保存的编辑，已保存报告需通过报告 ID 重新打开。API 尚无患者报告列表或独立备注字段，交接备注使用 SBAR 文本。时间线接口仅返回原始记录引用，完整原始记录通过证据抽屉查看。客户端显示上海时区时间。未建立真实患者资料、临床认证或 EHR 写入。
