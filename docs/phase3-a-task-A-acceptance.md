# 第三阶段 A 项断点复核与验收：未通过

日期：2026-10-16。先完整读取断点、任务 1 清点及对齐规格，再运行以下检查。仅模拟账号、隔离数据；没有登录真实账号、打开真实创作者后台或发布；没有访问或修改 ALQQ。

## 断点校正

`phase3-resume-checkpoint.md` 中“代码改动已完成”“全仓残留为零”不能作为验收结论。实际只完成部分 Python 启动参数清理。上一轮提及小红书分析器“一并处理”的说法不准确：其源码仍有固定 UA 和伪造指纹，尚未删除。本轮没有掩盖或停用该功能来冒充通过。

## 命令与真实输出

工作目录均为 `D:\Codexspace\Easel`；`PYTHONIOENCODING=utf-8`。下列均为模拟测试，没有真实浏览器或平台操作。

```powershell
.venv\Scripts\python.exe -m pytest tests/test_browser_policy.py -q --basetemp=tmp/phase3-a-policy-only
```

实际输出：
```text
...........................                                              [100%]
27 passed in 0.10s
```

```powershell
.venv\Scripts\python.exe -m pytest tests/test_browser_policy.py tests/test_browser_manager.py tests/test_account_network.py tests/test_channels_browser.py tests/test_platform_qr_validation.py tests/test_account_login_fixes.py tests/test_account_stats_fetch.py tests/test_account_stats_login.py tests/test_xhs_identity_state.py tests/test_web_publisher_assets.py tests/test_channel_accounts.py -q --basetemp=tmp/phase3-a-tests-focused -o faulthandler_timeout=20
```

实际最终输出：
```text
13 failed, 291 passed in 10.67s
```

完整真实输出（包括每个失败的堆栈）：[regression-focused.txt](phase3-a-evidence/regression-focused.txt)。策略单测原始输出：[policy.txt](phase3-a-evidence/policy.txt)。不得将上述结果写成“既有测试已跑通”。较早两次包含更多登录测试的运行在无进度时被终止，不能算通过；本次有最终统计的回归命令如上。另一次较小范围运行结果为 `12 failed, 187 passed in 12.39s`，不是修复后通过结果。

失败分类：
- `test_channels_browser` 两例：旧测试要求强制直连参数，以及 mock 已删除的 `_cloak_executable`。
- `test_account_login_fixes` 五例、`test_account_stats_fetch` 五例、`test_account_stats_login` 一例：mock 浏览器对象缺少 BrowserManager 需要的 `browser.new_browser_cdp_session()`；不能删除生产账号锁来迁就 mock。仍需修正测试边界后再跑。
- 新增 27 例覆盖合法窗口/下载参数、audit_options、时区、locale、language、UA、WebGL、硬件、client hints、代理、启动 argv 及非法参数在占用/启动前拒绝。

## 全仓搜索证据与处置状态

证据：[full-repo-search.json](phase3-a-evidence/full-repo-search.json)，只记录文件、行号和类别，不导出凭据或整行内容。遍历仓库文本文件（含隐藏文件、vendor、docs、outputs、tmp）；排除 `.git`、`.venv`、`node_modules`、字节码/pytest 缓存、cookie/auth/storage_state/环境秘密文件。不是对二进制或第三方依赖内部实现的审计。

搜索词类别为自动化标识（AutomationControlled、webdriver、stealth、Cloak）、环境覆盖（timezone、locale、language、UA）、硬件/WebGL/client hints 和浏览器代理。得到 381 条位置匹配：skills 123、tmp 164、tests 35、outputs 31、docs 12、web 10、scripts 4、easel 1、CHANGELOG 1。匹配数不是违规数，也不能声称全仓零残留；该清单是本次修复前复核快照。

| 位置/类别 | 已做或保留理由 | 结果 |
|---|---|---|
| shared/scripts 的 account_stats、douyin_publish、web_publisher、weixin_mp_stats、xhs_comment、xhs_publish、zhihu_answer | LAUNCH_ARGS 清空，删除 locale 覆盖；显式代理参数拒绝，不再从环境自动转换浏览器代理 | 部分完成，仍需全调用链回归 |
| zhihu_comments_fetch | 删除 AutomationControlled 和旧启动 args | 已改，未据此宣称全仓通过 |
| xhs_publish | 删除 Cloak 内核探测/选择分支 | 已改；相应旧测试尚未修正 |
| web/browser_policy.py:16、25；web/browser_manager.py:212–214 | 白名单校验在占用前执行；审计 options 构造器不设置设备/语言/时区/代理 | 27 条策略测试通过；独立审计执行入口仍未完成接线 |
| account_network.py:6–18；web/app.py:4737–4738 等 | 仍有账号代理模式/URL 下传及注入；没有完成清除，不能认定合规 | **未通过** |
| render_card.py:61–64 | 仍有浏览器代理注入；尚未清理 | **未通过** |
| 小红书分析器 signing/client | 固定身份和模拟硬件仍在，详见下一节 | **未通过** |
| 分析器 render.ts:598、cdp-cookies.ts:164 | 仍有 disable-gpu；后者旧搜索表达式没有完整捕获，人工追加复核发现，不能漏报 | **未通过** |
| skill-douyin-upload、skill-xhs-publisher、skill-xhs-comment-reply、skill-zhihu-answer 的说明/AGENTS | 仍有推荐反检测的旧文档；用户本次要求优先于旧指令 | 待清理，不能保留为业务需要 |
| 窗口大小、下载目录、profile 目录 | 用户允许的正常布局、文件保存、账号状态隔离；白名单保留，不用于伪造设备身份 | 可保留 |
| ASR/TTS/字幕语言、普通图片渲染分辨率 | 内容语言/输出像素，不是账号浏览器语言或设备伪造 | 可保留 |
| 模型服务代理、官方微信 API 出口、通知/RSS HTTP 网络配置 | 服务端网络连接，不是多账号代理防关联；仍需与浏览器入口隔离，不可作为浏览器代理保留理由 | 正常业务候选，尚未全链路验收 |
| easel/gateway_questions.py 的 easel-web/0.1 | 网关协议客户端名称，不是浏览器 UA 伪装 | 可保留 |
| tests 中拒绝参数字面量 | 负向验收输入，必须证明拒绝，不能只为 rg 零匹配而删测试 | 可保留 |
| docs/tmp 历史快照、outputs 平台资源缓存、frontend/dist | 历史记录和生成物，不等于活跃源代码；未执行旧发布/回滚脚本，不认定已清理 | 历史保留须标识；生成产物待重建 |

## 小红书分析器：改动前后逐项对比

本轮复核的“前”和“后”源码相同，**没有真正清除**。具体文件为 `skills/builtin/skill-xhs-analyzer/src/lib/`：

| 文件/行 | 改动前 | 当前改动后 |
|---|---|---|
| signing.ts:76–77 | 固定 Chrome/142 + Edg/142 USER_AGENT | 原样保留 |
| signing.ts:395、400–418 | generateFingerprint 随机选 GPU、屏幕、deviceMemory、cores、WebGL hash | 原样保留 |
| signing.ts:426–447、477 | 将 UA、内存、GPU、CPU、屏幕、时区等填入签名环境 | 原样保留 |
| signing.ts:671–676 | signMainApi 调用 generateFingerprint，编码进 x-s-common | 原样保留 |
| client.ts:8、60、439、510 | 导入 USER_AGENT，三个请求路径发送固定 user-agent | 原样保留 |

这是实际调用依赖，不能只删常量或改个真实 UA 就完成清除。直接删除指纹生成会破坏当前私有 API 签名请求；保留它又违反本阶段硬约束。需要将受影响分析读取路径改为不伪造环境的实现并单独验证，或明确批准停用该私有签名功能。未经决定不静默降级，不另造指纹替代。

## 验收逐项自查

| 验收项 | 实测证据 | 通过 | 未通过原因 |
|---|---|---|---|
| 断点先读、未重头开发 | 已读取三份指定文档后才新增测试 | 是 | — |
| 10 个改动文件相关回归跑通 | 上述 304 例统计 | 否 | 13 失败，较广范围另有中止测试，不能算全通过 |
| 新策略正负用例 | policy.txt，27 passed | 是 | 不代表全入口验收 |
| 全仓痕迹全部处置 | 搜索清单及上表 | 否 | 代理、分析器、旧指令和生成物未完成 |
| 分析器固定 UA/伪造硬件清除 | 上述具体行号及调用链 | 否 | 私有 API 签名依赖仍在 |
| 独立审计启动路径 | options 构造器和中央校验存在 | 否 | 仅有构造器，不足以证明所有入口无旁路 |
| 临时审计残留清理 | 见下节 | 是 | 历史日志已转存 |
| 不触碰真实账号/平台/ALQQ | 全部为源码读取、模拟测试、本地进程检查 | 是 | — |

## 临时物处理

删除前检查两个目标的规范化绝对路径均在 Easel/tmp 内且非重解析点，并以本机进程清单确认无浏览器占用 `phase3-audit`。将原 results.json 和 offline-0 至 offline-5 原始日志转存到 docs/phase3-a-evidence，保留任务 1 的可追溯证据；随后删除 `tmp/phase3-audit-run.py` 与 `tmp/phase3-audit/`。验收测试的新隔离目录与日志是独立名称，未误删真实账号 profile。

## 停止点

**A 未通过，不部署、不进入 B/C/D/E，不解除第二阶段门禁。** 按用户“遇依赖缺失或验收无法满足，必须立刻停下报障”的要求，报告分析器签名依赖与回归失败。下一步需先确定分析器非伪造读取替代方案，再清除剩余代理入口、修复测试并重做 A 验收；不得把当前文档当作批准进入 B 的依据。
