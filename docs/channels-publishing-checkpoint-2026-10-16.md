# 视频号优先：提交前准备路径

2026-10-16。范围仅 Easel；没有调用 ALQQ，没有真实账号登录、平台上传或发布。用户最新要求先集中做视频号，未解除此前“全程模拟账号/隔离数据、禁止真实账号登录及真实平台发布”的约束。

## 本次实现

文件 `skills/shared/scripts/web_publisher.py`：
- publish 支持 `--prepare-only` / `--stop-before-submit`，两者同义，仅视频号可使用。不是提交授权。
- 视频号专用路径先核验登录和可读账号身份；身份未知时在上传前终止。
- 发表视频导航入口要求唯一可见。转码后重新取得创作 iframe，按唯一描述框和精确角色/名称定位发表控件。
- 原生 fill 后读回描述，核对标题/正文/话题拼接结果；不一致立即停止。仅对明确 frame 重载异常重试准备，不吞掉其他错误。
- 最后只 focus 发表控件并返回 JSON；没有点击发表、Enter、合成事件或 JS submit。原“未跳转就换 frame 再 Enter”的路径已删除。
- JSON 包含实际账号名/ID、标题、正文、话题、媒体、读回描述、请求的封面来源/声明/可见性、提交控件与阻塞原因。
- 尚未实页核验的字段明确 `verified: false`，状态为 `waiting_settings_verification`，不能称为全部字段已填或可提交。自定义封面未支持时直接拒绝，不能静默忽略。
- 准备结果从完整执行入口提前返回，不进入成功判定或发布日历；关闭浏览器仍由原 finally 执行。正常提交入口继续经过第二阶段门禁；直接调用专用函数且没有严格的布尔 prepare_only=True 也会拒绝。

## 测试

新增 `tests/test_channels_preparation.py`，使用纯 Mock/模拟账号和临时媒体，未启动浏览器。覆盖准备读回、无提交调用、账号缺失、登录失效、封面不支持、文案不一致、入口歧义、异常不重试、CLI 两个别名、预览不写发布日历、跨平台不能借预览绕门禁、完整入口提前返回/关闭、默认提交门禁保留。

实际命令（项目根目录，PYTHONIOENCODING=utf-8）：

```powershell
.venv\Scripts\python.exe -m pytest tests/test_channels_preparation.py tests/test_web_publisher_assets.py tests/test_browser_policy.py tests/test_browser_manager.py tests/test_publish_queue.py tests/test_publish_snapshot.py tests/test_publish_receipts.py -q --basetemp=tmp/channels-preparation-tests-final
```

实际输出：

```text
........................................................................ [ 61%]
..............................................                           [100%]
118 passed in 1.69s
```

该范围不是全仓测试；不撤销 A 项验收文档记录的其他失败与残留问题。

## 验收界限与下一步

| 项目 | 结论 |
|---|---|
| 模拟调用链中提交前停点、完整参数输出、不写成功记录 | 已验证 |
| 视频号旧 frame 重试中的重复 Enter | 路径已移除；尚未新增真实提交入口 |
| 最小可见性、声明、封面字段全部应用并读回 | 未完成，不能填写“已验证” |
| 持久化 attemptId 后仅一次提交 | 未接线；现阶段不会提交 |
| 本人作品列表读回与回执自动落库 | 未接线 |
| 真实页面选择器有效性/发布可用 | 未验证；不能声称可用 |

真实可见性/声明控件是下一依赖。目前没有已核验的页面证据，不能照抄规格枚举认定实页可用。现有限制禁止登录真实账号，故不能在本轮自行完成实页验收。后续如获准使用一个测试视频号，仅检查页面、准备到提交前（仍不发表），才可核验对应控件；最终真实提交仍需另行明确确认完整参数。确认前不放开队列自动发布、不修改能力矩阵为 automatic=true、不部署声称已打通的版本。
