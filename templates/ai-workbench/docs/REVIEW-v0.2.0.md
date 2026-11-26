# v0.2.0 复查与验收

日期：2026-10-27。触发问题：用户反馈“Codex接入后用不了”。范围为独立模板，不修改Easel主工作台。

## 检查发现与修复

| 问题 | 修复与验证 |
| --- | --- |
| CLI安装状态不能说明已经认证，失败缺少明确诊断 | 增加所选引擎检测；Codex实际运行login status，只返回认证结论，不回传凭据或原始输出 |
| 新建会话异步完成时可能切换输入上下文，丢失已输入内容 | 建立会话期间禁用编辑；按会话、媒体和业务页面分别保存草稿；真实UI回归 |
| API模型可能与原生模型混淆 | 各原生引擎独立保存模型覆盖；默认留空采用原生配置；增加API模型读取 |
| 页面切换可能混用任务结果，业务历史缺少来源 | 任务详情独立、来源持久化、后台状态刷新、权限选择跨轮询保留 |
| 生成文件列表漏根目录和深层文件，媒体缺少预览 | 递归枚举允许的生成目录，保留下载文件名，图片/音频/视频提供安全类型预览 |
| 缺少技能导入、会话重命名和导出 | 支持提示词Markdown技能保存和目录搜索；会话重命名与Markdown导出 |
| 未配置通道仍能提交，图片接口兼容面不足 | 暴露能力与配置状态，未就绪禁止提交；图片支持b64和URL；音色可配置 |
| 同端口旧服务、同ID复制目录可能打开错误实例 | 健康接口加入安装目录指纹和PID；启动拒绝其他目录，停止校验归属及活动任务 |

这些是本轮确实复现或检查发现的问题；不能仅凭用户一句反馈断言其原环境只存在其中某一个原因。真实Codex页面流程已经验证，安装和认证仍是每台机器自己的前置条件。

## 测试方法与结果

以下命令从模板根目录执行。测试运行器使用原项目已安装的pytest/Playwright；被测服务使用模板独立虚拟环境，且复制目录启动前断言workbench包来自该目录。

```powershell
..\..\.venv\Scripts\python.exe -m pytest tests -q --tb=short --basetemp=../../tmp/template-review-tests-final --disable-warnings --maxfail=2
..\..\.venv\Scripts\python.exe scripts/verify_ui.py --python .venv/Scripts/python.exe
..\..\.venv\Scripts\python.exe scripts/verify_codex_ui.py
..\..\.venv\Scripts\python.exe scripts/verify_codex_ui.py --tools
..\..\.venv\Scripts\python.exe scripts/verify_install.py
```

- 后端真实输出：`30 passed in 17.68s`，见evidence/backend-results-v02.txt。
- 界面三轮全部通过，覆盖配置、模型读取、技能导入、聊天/刷新/导出、媒体草稿隔离、图片加载、业务任务历史、工具确认与窄屏布局。模型API与ACP服务均为本机模拟，浏览器外部请求0。
- 真实Codex只读页面测试：CLI认证成功、原生默认模型回复、刷新恢复，额外权限批准0。见evidence/codex-real-ui.json。
- 真实Codex文件测试：隔离复制目录，工作区写入，创建outputs/generated/template-check.txt；核对UTF-8内容和产物接口，刷新后回复仍在，额外权限批准0。见evidence/codex-tools-ui.json。没有社交账号登录或平台发布。
- 全新目录执行交付的setup.ps1，独立安装锁定依赖；中文+空格路径、预构建UI免Node启动、重复启动复用PID、同ID不同目录拒绝、错误目录不能停止服务、正确目录优雅停止均通过。见evidence/install-results.json。
- 最终ZIP另行解压启动验证，结果见evidence/release-results.json；发布清单在压缩包旁的release/release-manifest.json。

人工查看了Codex真实工具任务与窄屏截图，未见横向溢出或消息区域被挤成窄条。测试中曾遇到Windows子进程继承PIPE导致验收脚本等待不退出，已把验收日志改为普通文件；这不是服务故障。

## 使用方法与交付边界

新版先安装，再启动。在AI设置选Codex，原生模型覆盖留空，保存并检测；需要时在同一Windows用户终端执行codex login。切换引擎后新建对话。需要生成文件时选择工作区写入，额外权限仍需逐项确认。

只刷新页面不会升级旧Python服务：旧模板先停止，再从新目录启动；不同工作台使用不同端口。包不含用户登录凭据和运行数据。

114项为技能目录，只有3项完整技能随包交付；视频/音乐供应商、真实WorkBuddy/OpenCode、真实Codex生图和其他操作系统未完成实测，不归入已通过项目。
