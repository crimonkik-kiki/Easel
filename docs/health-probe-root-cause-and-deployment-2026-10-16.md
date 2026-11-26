# 健康探针根因与重新部署结果

日期：2026-10-16。变更及材料均位于 D:/Codexspace/Easel。未修改 ALQQ，未登录真实账号或向真实平台发布内容。

## 先只读定位的证据

环境为 Windows PowerShell **5.1.26100.9711**、CLR **4.0.30319.42000**。默认 `Invoke-WebRequest` 的实际异常类型为 `System.NullReferenceException`，关键调用栈是：

```
Microsoft.PowerShell.ConsoleHostUserInterface.PromptForChoice
System.Management.Automation.MshCommandRuntime.ShouldContinue
Microsoft.PowerShell.Commands.InvokeWebRequestCommand.ProcessResponse
```

这证明异常来自响应处理触发的交互式确认路径及当前宿主的提示接口，不是脚本变量未初始化或已取得的响应对象字段为空。没有进一步猜测触发此确认的具体系统补丁或策略。

对同一运行服务做配对检查：

| 方式 | 结果 |
|---|---|
| PowerShell 默认 Invoke-WebRequest | 在上述 PromptForChoice 路径抛空引用 |
| 同版本 PowerShell 加 UseBasicParsing | HTTP 200，2543 字节 |
| 独立 .NET HttpClient（本地直连） | HTTP 200，2543 字节 |

两种成功请求的响应 SHA-256 完全相同：`a318bf163f0b555c9ae87b7b7166fb6b7aaf9ac144d942ecd4496d954c81d84b`。

不是仅凭根页面 200 认定服务健康：只读核查账号缓存、操作记录 JSON；全新浏览器检查账号页、发布页和操作记录入口成功，自动账号访问为 0。在本次检查范围内没有发现第 2 项服务功能故障，因而归类为 **(a) 探针自身异常**，没有将其归类为 **(b) 服务故障恰巧返回 200**。

## 修复与失败分类

- `web/health_probe.py` 使用标准库非交互 HTTP 请求，不依赖 PowerShell HTML 解析或交互提示。
- `health-easel.ps1` 在 PowerShell 5.1 非交互环境调用探针，校验 JSON 标记与退出码一致性；空输出、格式异常、未知退出码均不放行。
- 退出 0 / `HEALTHY`：所有目标合同通过。
- 退出 20 / `SERVICE_UNAVAILABLE`：连接失败或传输超时。
- 退出 21 / `SERVICE_UNHEALTHY`：服务响应了，但 HTML、脚本、接口 JSON、版本或页面合同不符。根页面 200 不能覆盖其他检查失败。
- 退出 30 / `PROBE_ERROR_MANUAL_REVIEW`：探针自身异常，明确 `requires_human_review=true`，不能默认为成功，也不能作为服务故障统计。
- `scripts/health_ui.py` 使用全新项目内浏览器目录、浏览器内模拟账号与任务。阻止所有外部请求、生产写请求和真实账号访问，验证实际部署的前端界面。

## 部署及回滚策略

`deploy-phase2.ps1` 在重启前检查活动操作、浏览器租约、队列运行任务及本机账号浏览器/脚本；候选源码有 SHA-256 清单。保存完整候选代码和旧版本回滚材料，避免上一轮回滚丢失集成入口。

只允许一次部署。启动时仅连接未就绪可在有限期限内等待；接口合同不符和探针自身异常立即停止门禁。部署后 HTTP 或 UI 门禁任一失败，就回滚一次并停止，不再次部署。探针异常会保留独立标记并要求人工判定；回滚本身也不能确认时输出 `ROLLBACK_UNCONFIRMED_MANUAL_REVIEW`。

## 本次实际结果

已恢复第 3/4/5 项集成改动，隔离测试再次通过。本次部署一次成功：**DEPLOYED_HEALTHY**，未触发回滚。

| 健康项 | 实际结果与范围 |
|---|---|
| 服务可用 | 实际 HTML、应用脚本、账号缓存和操作记录接口均通过 |
| 账号页、发布页不自动访问账号 | 部署前端 + 浏览器内模拟数据通过；自动账号访问 0 |
| 操作记录入口 | 弹窗可打开和关闭 |
| 发布队列 | 实际队列 API 合同通过；部署界面渲染模拟任务通过 |
| 任务详情 | 实际不存在 ID 返回约定的 404；部署界面打开模拟任务详情通过；真实任务读写已另在 7861 隔离服务验证 |
| 回执来源 | 明确显示“平台回执（人工核对）”及“已发布（人工核对）” |
| 数据边界 | 生产账号/任务写入 0，真实账号登录 0，真实平台发布 0 |

当前线上为第二阶段 **第 2～5 项版本**，平台能力版本 **2026-10-16-v1**。平台分级矩阵仍生效：没有凭未知封面或声明开启全自动发布。

发布材料：`tmp/release-probe-fixed-20261016-131618/`，包含 `candidate/`、`rollback/`、源码清单、空闲检查、`deployed-core-health.json`、`deployed-ui-health.json` 和服务日志。

测试：原 237 项 Python + 新增 10 项 HTTP 探针分类 + 2 项 UI 探针用例均通过（共 249 个独立用例）；15 项前端登录回归通过；7861 隔离服务的 HTTP/UI 门禁及编辑器至人工回执全流程通过。
