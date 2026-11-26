# v0.3.0 Easel 原版框架恢复验收

日期：2026-10-27。目标：保留Easel原有外观与通用交互，去掉具体业务；保留v0.2已修复的Codex接入与任务机制。

## 改动

直接抽取原版样式变量、264px侧栏、灰白侧栏底色、纸感渐变、字体栈、线性图标、品牌Logo、卡片、仪表盘、对话布局、内容画廊、设置弹窗与日夜主题。样式来源及哈希在extraction-manifest.json中记录。

会话列表回到侧栏；空对话居中欢迎，开始任务后消息滚动、输入框置底。设置从独立页面恢复为悬浮面板，六通道采用标签切换。保留配置保存/读取、CLI检测、模型读取、权限确认、技能导入、会话重命名/导出和生成文件下载。品牌、欢迎语、导航和业务入口改为配置驱动。

适配中补充了配置尚未加载时的设置入口防护、弹窗Escape/焦点约束与背景inert、窄屏滚动布局，修正夜间设置保存按钮的文字对比度。没有改变工具权限边界，也没有自动批准权限。

## 验证与证据

- 后端：命令及真实输出见evidence/backend-results-v03.txt；实际输出31 passed in 18.27s；新增实例品牌/导航投影测试，检查不会创建AI任务。
- 前端：`npm run build --prefix frontend`，通过TypeScript与Vite构建；产物随包交付。oxlint退出码0，保留1条既有API客户端警告（可选fetch body与动态GET方法的静态推断），没有修改该调用合同。
- 任务流程：`python scripts/verify_ui.py --python .venv/Scripts/python.exe`，三轮独立浏览器上下文，涵盖配置、模型读取、技能导入、聊天与刷新、媒体草稿隔离、图片加载、业务历史、ACP权限确认。API与ACP均为本机模拟，不冒充真实供应商。
- 视觉与通用交互：`python scripts/verify_visual.py`。验证264px侧栏、原版字体栈、文字色rgb(23,25,28)、9px基础圆角、#158f9a强调色；检查六通道、音色保存后读回、Escape返回、草稿保留、技能抽屉、日夜主题刷新恢复、内容库画廊与下载、390px窄屏无横向溢出。AI任务0，浏览器外部请求0。
- 真实Codex：在新版外观的隔离复制目录中执行 `python scripts/verify_codex_ui.py --tools`；认证成功、原生默认模型、工作区写入、创建并核对UTF-8文件、刷新恢复回复，额外权限批准0。结果见evidence/codex-tools-ui.json，截图为codex-tools-ui.png。
- 压缩包：最终ZIP解压到新目录后确认从解压目录导入包；首页、bootstrap、版本、品牌、静态Logo、空历史与停止入口检查见evidence/release-results.json。独立安装脚本与目录指纹机制沿用v0.2已验证流程。

截图位于evidence/：easel-home、easel-chat-empty、easel-settings、easel-skills、easel-files、easel-dark、easel-settings-dark、easel-mobile、easel-settings-mobile。画廊文件是隔离测试中创建的图片和Markdown，不是实际AI生成。主代理查看了截图；本轮没有独立评审或像素级一致性评分。业务内容与原Easel不同，不声称整页逐像素一致。

## 交付边界

只修改模板与本项目内的验证资料，不修改原Easel业务。社交账号、发布、画像、Clipify和运营分析不移入模板。114项仍为技能目录，3项完整通用技能随包；视频/音乐仍需实际供应商适配。真实WorkBuddy/OpenCode、原生生图及macOS/Linux没有新增实测结论。

原版字体栈保留，外部字体请求未移入；跨机器字体可能不同。品牌与扩展方法见UI-FRAMEWORK.md。v0.2故障修复的历史记录保留在REVIEW-v0.2.0.md。
