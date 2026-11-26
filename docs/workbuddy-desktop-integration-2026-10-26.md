# WorkBuddy 桌面账号接入断点（2026-10-26）

## 用户选择与当前结论

用户明确要求只使用现有 WorkBuddy 桌面账号，不接受独立 CodeBuddy CLI 登录。Easel 尚未接通 WorkBuddy 模型调用，未新增或启用 WorkBuddy 执行引擎，未切换当前工作台底座。

已验证 ACP 协议握手及空会话创建；隔离配置下的最小文本调用返回 `Authentication required`。这只能证明该测试进程没有可用认证，不能证明桌面账号无效，也不能证明任何正常配置下都无法复用桌面账号。

## 已有实测证据

- 探针：`scripts/probe_workbuddy.py`；证据：`tmp/workbuddy-probe/handshake-result.json`。
- 安装内的引擎包：`D:\workbuddy\resources\app.asar.unpacked\cli`，包版本 2.165.0。此版本号不是桌面产品版本。
- 命令：`.venv\Scripts\python.exe scripts/probe_workbuddy.py --serve --session`。
- 结果：`protocolVersion=1`、`sessionCreated=true`、`sessionError=null`。
- 命令：`.venv\Scripts\python.exe scripts/probe_workbuddy.py --serve --prompt`。
- 结果：`stopReason=refusal`；错误类别 `auth`，错误文本 `Authentication required`；回复为空。
- 文本测试禁用内置工具，不配置 MCP；使用项目 tmp 下隔离配置。没有读取、复制或注入桌面认证凭据，没有进行新的 CLI 登录。临时进程由探针关闭。
- 用户作出仅使用桌面账号的选择后，不再继续独立 CLI 登录或依赖该方案部署。

## 官方支持的桌面助理入口

2026-10-26 核对的官方资料：

1. [Open API 接口](https://open.workbuddy.cn/docs/openapi)：本地助理 API 面向用户 PC 端助理；接入前需要开发者账号、第三方应用的 clientId/clientSecret，并通过 OAuth 2.1 取得用户授权。
2. [第三方应用](https://open.workbuddy.cn/docs/third-party-app)：应用与权限需要提交审核；硬件接入面向厂商与合作伙伴，积分兑换应用不提供本地助理权限。不能假定个人项目一定能获得所需权限。

最小权限与调用链：

| 步骤 | 接口或权限 | 验证目的 |
| --- | --- | --- |
| 授权 | OAuth 2.1，`user.localassistant.readable`、`user.localassistant.invokable` | 授权 Easel 使用当前用户本地助理 |
| 查询在线 | GET `/openapi/v2/localassistant` | 返回 `online=true` |
| 最小文本测试 | POST `/openapi/v2/localassistant/message` | 向桌面助理发送固定测试文本 |
| 查询回复 | GET `/openapi/v2/localassistant/message` | 按消息标识核对回复 |

上述调用使用 WorkBuddy 官方 HTTPS 服务，并非仅靠本机端口完成。文档中的云端任务 ACP 是另一个执行环境，不能替代用户要求的桌面账号路径。

## 当前阻塞与恢复条件

尚未提供可用于 Easel 的已启用应用及本地助理授权。桌面登录完成不等同于第三方应用已获授权。需要先在开放平台确认该项目能申请本地助理权限；若可申请，则完成应用审核与 OAuth 授权，再验证在线状态及单次文本往返。

不要求用户在聊天中提供密码、clientSecret 或 access token。应用获批后再落实本机服务端的凭据配置及存储。

即便最小往返成功，仍需验证会话隔离、消息归属、工具权限响应、取消及产物读取，才能判断是否能达到 Easel 现有执行引擎的能力。当前文档没有为这些能力提供全量对等保证；额度归属也尚未验证。

本次没有修改 WorkBuddy 安装文件或 ALQQ，没有真实平台登录、发布行为，没有部署生产适配器。

---

## 补充：嵌入式 CLI 路线为何不可行（2026-10-26 复测）

上一轮把 `Authentication required` 归因于隔离配置目录没有凭据。本轮复测发现更本质的
阻塞：**内置 CLI 与桌面端自己的 prewarm 进程池互斥**。

证据：

- 桌面端以 `WorkBuddy.exe ... cli\bin\codebuddy --prewarm --prewarm-id wb-pool-*`
  常驻启动两个 CLI 实例（PID 22004 / 40128）。
- PID 22004 监听 `127.0.0.1:51507`，PID 33148（`daemon-app-server-entry.js`）与它保持连接。
- 用默认配置目录启动第二个 `--acp` 实例，立即报
  `Error: listen EADDRINUSE: address already in use 127.0.0.1:51507`。
- 指定其它端口后，即使沿用 11:14 曾经成功的原始探针，也退化为
  `ACP did not answer initialize`（进程存活但不应答）。
- 探针目录内出现 `plugins/cache/.../.in_use/<pid>` 单例标记；清空隔离目录不能恢复。

结论：只要桌面端开着，就无法稳定并行启动第二个 ACP CLI 实例。关掉桌面端才有机会，
但这与「用桌面账号」的前提直接冲突。该路线不作为交付方案。

## 落地：官方 Open API 本地助理适配器

改为走文档化的本地助理 API，不抢占桌面端本地资源，不依赖 CLI 版本。

| 改动 | 文件 | 说明 |
| --- | --- | --- |
| 新增适配器 | `easel/harnesses/workbuddy.py` | `WorkBuddyAdapter`，实现 `Adapter.run` 契约 |
| 注册底座 | `easel/harnesses/store.py` | `IDS` 增加 `workbuddy` |
| 注册适配器 | `easel/harnesses/__init__.py` | `ADAPTERS` 注册；`describe()` 对 workbuddy 按凭据判断 installed |
| 端到端验证 | `scripts/check_workbuddy.py` | 五步检查，只读探测，不打印凭据 |
| 配置样例 | `.env.example` | 补充 `WORKBUDDY_*` 四个键 |

运行时行为：

1. 用 `refresh_token` 换 `access_token`，缓存在 `outputs/_harness/workbuddy-token.json`（0600），
   提前 60 秒刷新；
2. `GET /localassistant` 确认桌面端在线；
3. `POST /localassistant/message` 提交本轮提示（前缀沿用 `harness_instructions`）；
4. 以返回的 `message_id` 轮询 `GET /localassistant/message`，取到 `role=assistant` 即回填；
5. 按段落切分后逐段 emit，让前端有流式观感。

如实声明的能力差距：

- 接口没有 token 级流式，只能用段落回填；
- 没有会话 ID，消息进入桌面端当前会话，Easel 无法隔离私有原生会话，也不支持按原生 ID 续接；
- 不能在 Easel 侧切模型（设置模型覆盖会明确报错）；
- 工具权限由桌面端自行弹窗，Easel 的 `ask` 通道本轮不参与。

## 验证结果

- `describe()` 六个底座全部可枚举，`workbuddy` 在无凭据时 `installed=false`（符合预期，
  未配置不给选）；
- `python scripts/check_workbuddy.py` 在无凭据时报出缺哪三个键及取得方式，不崩溃；
- harness 相关测试 94 passed / 6 skipped；完整回归 1267 passed、98 skipped，
  余下 2 项 `test_login_qr.py` 失败为既有缺陷（`web/app.py:4713` `_ANALYTICS_BUSY` 未定义），
  另 1 项 `test_codex_permissions.py` 因 Windows 无 `os.symlink` 特权跳过比对，均与本次改动无关。

## 仍未解除的前置条件

OAuth 授权凭据尚未取得，因此**未做任何真实模型往返**。需要先确认该项目能申请到本地助理
Scope（硬件接入类应用），完成应用审核与授权后，用 `scripts/check_workbuddy.py --send`
验证真实往返，再切换底座。
