# AI 工作台模板 · v0.3.0

从 Easel 提取的独立工作台框架。保留 AI 执行、技能和交互底座，用业务模块替换具体场景。复制后的项目不需要原 Easel 目录存在。

## 下次新建工作台，只做这三步

1. 解压发布包，运行一次 `安装工作台.cmd`。需要 Python 3.10+；发布包已包含构建好的前端，普通使用不需要 Node.js。运行依赖已记录在 requirements.lock。需要关闭时运行 `停止工作台.cmd`；存在运行中任务时会拒绝关闭。
2. 创建新项目（目标目录必须不存在）：

   ```powershell
   .\.venv\Scripts\python.exe scripts\create_workbench.py "D:\Codexspace\客户服务工作台" --name "客户服务工作台" --port 7871
   ```

3. 在新目录运行 `安装工作台.cmd`，然后双击 `启动工作台.cmd`。进入 **AI 设置** 选择执行引擎、模型和媒体通道。

新项目会获得独立 ID、端口、配置、数据库与输出目录。创建脚本不复制 `.env`、密钥、原生登录缓存、历史、附件、虚拟环境或依赖目录。

需要定制业务时，照 `workbench/modules/brief.py` 新建一个模块，在 `workbench.json` 的 `modules` 中登记即可。标准表单、左侧导航、AI任务与结果展示会自动接入，见 [扩展指南](docs/EXTENDING.md)。

## 已保留的 AI 能力

| 层 | 模板内容 |
| --- | --- |
| AI 对话 | 流式回复、Markdown、安全渲染、会话保存、历史续接、文本附件、技能选择 |
| Agent 执行 | Easel 原有 Codex 原生 app-server、OpenCode ACP、通用 ACP、WorkBuddy 本地助理适配器 |
| 权限与执行记录 | 工具确认、用户问答、停止任务、执行活动、会话底座绑定、私有 stdio 进程复用与清理 |
| 技能 | SKILL.md 发现、查看、向对话注入、Agent工作区规范、导入脚本；附 Easel 全部 **114 个技能目录索引** |
| 媒体 | 图片API、Codex原生生图、语音合成API、语音转写API；视频和音乐预留供应商注册接口 |
| 配置 | 六个AI通道独立配置；前端不读回Key；空白保留、明确勾选才清除 |
| 任务 | SQLite 持久化、SSE事件回放、会话互斥、重启中断标记，不自动重发 |
| 工作台外壳 | 左侧导航、深浅主题、首页、技能库、任务记录、生成文件、设置与业务模块 |

模板内置三项通用技能：文本润色、文本摘要、论文解读。技能页也支持新建/导入提示词规范，并显示114项索引的实际安装状态。索引中的其他技能尚未安装，不能把“114个索引”理解为“114个技能已具备运行依赖”。

按需从受信任的 Easel 副本导入完整技能目录：

```powershell
.\.venv\Scripts\python.exe scripts\import_skill.py --source "D:\Codexspace\Easel" --name chart-visualization
```

导入只复制文件，不执行脚本或自动安装依赖。依赖 `skills/shared/scripts`、FFmpeg、Python包、浏览器、模型或第三方服务的技能，需要按其文档另行准备。参考 [技能目录索引](docs/easel-skill-catalog.json)。

## 原版外观与定制

v0.3直接抽取Easel原版的样式变量、侧栏、卡片、对话区、设置弹窗、线性图标和日夜主题，保留v0.2修好的Codex接入。品牌与业务入口可配置，不需要重新设计一套前端。

默认侧栏为工作台、对话、技能库、AI媒体、任务记录、内容库；设置入口在左下角，媒体模型在悬浮设置面板的六个标签内配置。业务模块会自动添加侧栏入口。账号发布、画像等具体业务没有移入模板。

修改方法见 [品牌与框架配置](docs/UI-FRAMEWORK.md)，本轮截图与测试见 [v0.3验收](docs/REVIEW-v0.3.0.md)。

## 配置 AI

- **模型 API**：填写兼容 Chat Completions 的服务基础地址（通常以 `/v1` 结尾）、模型、Key。它不执行本机命令或浏览器工具。文本附件最大256KB。
- **Codex / OpenCode**：在运行工作台的同一系统账户下安装并认证对应 CLI。模板不复制 CLI 的凭据，不会自动登录；原生模型覆盖按引擎分别保存，留空沿用原生默认值，不会误用API通道的模型。默认不自动批准额外权限。
- **通用 ACP**：本机管理员在 `outputs/_harness/acp.json` 写入 `{"command":["可执行程序绝对路径","参数"]}`。不走 shell；Windows 用程序或 `node` 加脚本，不能直接写 `.cmd`。
- **WorkBuddy**：保留本地助理 Open API 适配器；需要应用 OAuth 授权、对应 scopes、PC客户端在线及 `.env` 中的 `WORKBUDDY_*` 凭据。仅桌面登录不会自动完成第三方调用授权。桌面助理不是每条对话独立的原生会话，因此执行通道串行，不能承诺对话隔离或上下文续接。
- **图片 / 语音 / 转写**：使用各自通道的基础地址与模型。API图片通道支持 `b64_json` 和图片 `url`，可选择自动响应格式；语音接口使用 `audio/speech`，转写使用 `audio/transcriptions`。Codex生图不回退到付费图片API。
- **视频 / 音乐**：供应商协议不统一，模板保留配置与注册合同，需要适配后使用。未注册时明确失败，不显示伪造结果。

`.env.example` 是空白配置说明，真正的 `.env` 需要自行创建。可在设置页点击“检测所选引擎”核对Codex CLI是否认证。模型API配置也可以在UI保存，位于当前项目的 `outputs/_config/settings.json`；该文件含明文凭据，应限制操作系统文件权限并禁止提交或分发。原生Agent是否具备某个工具或模型，取决于其安装、认证和账户能力。

## 源码结构

```text
workbench.json          品牌、Logo、导航、实例ID、端口、业务模块
workbench/
  app.py                本机API、SSE、附件与文件隔离
  engine.py             对话/技能/媒体共用任务执行层
  config.py             通道配置、凭据脱敏
  storage.py            SQLite与单实例数据锁
  harnesses/            提取并解耦的原生Agent适配器
  direct_api.py         提取的模型API流式对话与历史
  codex_images.py       提取的原生生图与结果验证
  modules/              你的业务模块
frontend/src/           Easel原版视觉框架 + 独立React页面与API客户端
skills/builtin/         可插拔技能与引用资料
agents/workspace/       所有Agent共享的执行约定
scripts/                复制项目、导入技能、打包脚本
tests/                  本机模拟服务与协议测试
outputs/                实例运行数据，永不打进模板包
```

## 开发与验证

```powershell
# 修改前端后重新构建（Node.js 22.12+，建议24 LTS）
.\setup.ps1 -RebuildUI

# 安装测试工具并运行离线后端测试
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m pytest tests -q

# 后端前台运行；默认127.0.0.1:7870；启动器会核对安装目录，拒绝复用其他目录占用的端口
.\.venv\Scripts\python.exe -m workbench

# 重新打包，只包含源码与已构建UI
.\.venv\Scripts\python.exe scripts\package_template.py
```

macOS/Linux 可用 `python3 -m venv .venv`、`.venv/bin/python -m pip install -e .`、`.venv/bin/python -m workbench`。Windows一键脚本和本轮验证针对Windows；其他系统未进行实际启动验证。

本框架默认只服务本机单用户，不是可直接公网部署的多租户SaaS。它复用原生Agent权限机制，不把 ACP 的权限声明当作操作系统级沙箱。不要复制本机的运行数据给其他人。

## 来源与验收

原始项目：[ZJU-REAL/Easel](https://github.com/ZJU-REAL/Easel)。保留 Apache-2.0 [LICENSE](LICENSE)；抽取文件、源文件哈希及改动说明见 [来源清单](docs/extraction-manifest.json)。业务发布、社交账号登录、平台浏览器自动化、Clipify媒体流水线和运营分析不属于框架核心，未移入模板。

独立安装、复制启动与UI验证证据见 [验收说明](docs/ACCEPTANCE.md)。真实模型和原生账户调用需要使用方配置；离线测试通过不代表每家供应商都已实测兼容。


## Codex接入后不能使用时

1. 在 **AI 设置** 中选择 **Codex**，原生模型覆盖先留空，点击 **保存 AI 配置**。
2. 点击 **检测所选引擎**。若CLI未认证，在同一Windows账户的终端完成 `codex login`；仅登录桌面App不等于CLI已认证。模板不读取或复制其他App的登录凭据。
3. 切换执行引擎后点击 **新对话**。旧会话固定属于原引擎，不会暗中迁移到Codex。
4. 普通问答可选只读；需要创建交付文件时选择工作区写入。额外工具授权仍逐次确认，模板不自动放行。
5. 确保运行的是新版本后端：健康接口应显示0.3.0。旧服务需先停止；只刷新网页不会升级已运行的Python服务。两个目录即使名称/实例ID相同，也不能共用同一端口。

v0.2.0已在本机真实验证Codex的CLI认证、页面对话、刷新恢复，并测试生成文件流程。其他机器仍需要具备相应CLI安装、认证和账户模型权限。

## v0.2.0 功能修复（已包含在新版中）

- 修正新建会话时异步切换导致输入可能丢失；对话与媒体按上下文保存草稿。
- 任务详情独立，业务任务记录保留来源；切换页面不混用结果，后台任务状态会更新。
- 生成文件递归列出根目录及深层文件，图片/音频/视频可预览，下载保留文件名。
- 支持对话重命名、Markdown导出、新技能保存、技能目录搜索、API模型读取、自定义音色及图片URL响应。
- 未接适配器或未配置的通道不可提交；视频/音乐仍需具体供应商适配，不冒充可用。
- 一键启动核对目录指纹，防止误开另一个工作台；增加安全停止脚本。

历史功能修复见 [v0.2复查](docs/REVIEW-v0.2.0.md)；当前外观与交互验收见 [v0.3复查](docs/REVIEW-v0.3.0.md)。
