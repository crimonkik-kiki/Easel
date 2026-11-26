# 视频号取数失败排查与修复

2026-10-21，用户反馈视频号数据读取失败。

## 已确认的证据

- 本地运营数据库最近一条视频号同步记录为 HTTP 异常分支，原日志仅保存「平台读取失败」通用提示，没有保留具体异常。不能根据该记录断言是网络、登录过期或页面变化。
- `outputs/_install/local-resources.json` 配置 `EASEL_CHANNELS_BROWSER_CHANNEL=msedge`。登录脚本 `web_publisher._browser_options()` 读取此配置并使用原生 Edge。
- 原 `account_stats._scrape()` 不读取该配置，直接使用 Playwright 的 Chromium，附带语言、禁图、GPU、自动化标识及旧代理等覆盖。登录与取数的浏览器/网络路径不一致是实际代码缺陷，但历史日志不足以证明它是本次失败的唯一原因。
- 服务环境中的 Chromium 1248 文件存在，Edge 也已安装。因此不能把本次问题简单判定为「没有安装浏览器」。

## 修复

1. `account_stats._browser_options()` 读取与登录相同的平台浏览器 channel 配置；视频号默认原生 Edge。原生路径不设 locale、GPU、身份或旧代理覆盖，复用账号正常网络策略，保留原账号 profile 选择。
2. 视频号登录检测加入已存在于登录适配器中的二维码 iframe 与账号导航选择器。
3. `web/analytics_errors.py` 从完整异常而非最后一条进程退出日志分类：浏览器缺失、目录占用、网络失败、浏览器提前退出、导航超时。
4. HTTP 同步失败记录保留状态码及脱敏后的具体原因，不再统一替换成通用提示。链接、凭据与本地绝对路径从存储诊断中清理。旧错误记录保留原样，不倒填未知原因。

改动：`skills/shared/scripts/account_stats.py`、`web/app.py`、`web/operations_api.py`、新增 `web/analytics_errors.py`。

## 验证与部署

```powershell
.venv\Scripts\python.exe -m pytest tests/test_channels_analytics.py tests/test_operations.py tests/test_operations_integration.py tests/test_web_analytics.py tests/test_account_stats_fetch.py tests/test_account_stats_login.py tests/test_account_whoami.py tests/test_channel_accounts.py tests/test_channels_browser.py tests/test_account_network.py tests/test_analytics_transport.py tests/test_mp_login.py -q --basetemp=tmp/channels-stats-release-tests
```

实际结果：`184 passed in 2.00s`。

```powershell
.venv\Scripts\python.exe scripts/verify_channels_stats.py
```

真实 Edge 加载本地 HTML fixture、实际 DOM 解析、数据规范化和 SQLite 入库通过。模拟粉丝 128、作品数 3；没有真实账号 profile 访问，也没有平台网络请求。证据：`tmp/channels-stats-iqyzx9cy/result.json`。

部署：`tmp/operations-release-channels-fix-20261021-114644`，保存修复前的三个后台文件精确副本及旧 dist。原分析数据库、历史及账号资料保留。

部署后被动健康检查 `HEALTHY`：服务、候选前端、分析账号与报告、账号列表、技能列表均通过；没有调用取数、登录或发布接口。

**剩余实测边界：**没有访问真实创作者后台。原始错误的完整文字尚未收到；真实账号重试的结果未验证。若仍失败，新记录的错误分类与具体原因可用于继续定位，不能把离线通过当作真实平台恢复成功。
