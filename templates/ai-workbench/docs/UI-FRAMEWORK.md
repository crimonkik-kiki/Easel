# 保留 Easel 外观，套用到新的工作台

模板0.3.0保留Easel原版的设计变量与界面结构，业务数据接到独立模板API。外观来源与文件哈希见 `extraction-manifest.json` 的 `ui_extraction`。

## 先改配置，不改框架

`workbench.json` 示例（保留实际工程的唯一id）：

```json
{
  "id": "workbench-your-unique-id",
  "name": "客户工作台",
  "subtitle": "团队的 AI 工作入口",
  "logo": "/brand/customer-logo.svg",
  "welcome_title": "今天，想一起完成什么？",
  "welcome_subtitle": "整理客户信息，推进下一步工作。",
  "port": 7871,
  "navigation": [
    {"id": "home", "label": "项目总览", "icon": "dashboard"},
    {"id": "chat", "label": "对话", "icon": "chat"},
    {"id": "skills", "label": "技能库", "icon": "skills"},
    {"id": "media", "label": "素材工坊", "icon": "image"},
    {"id": "jobs", "label": "任务记录", "icon": "calendar"},
    {"id": "artifacts", "label": "内容库", "icon": "outputs"}
  ],
  "modules": ["workbench.modules.brief"]
}
```

- `name` 同时用于窗口标题、侧栏和对话欢迎区；`logo` 用于侧栏、欢迎区和网站图标。
- 本地Logo放入 `frontend/public/brand/`，对应URL为 `/brand/文件名`；添加或替换资产后重建前端。只改名称、欢迎语、导航配置不需要重建，但应重启服务并刷新页面。
- `navigation` 决定通用入口的顺序、名称与是否显示；省略或置空时采用默认入口。支持的id为上述六项，未知id忽略，重复id只用第一项。它只控制导航展示，不是API访问控制。
- 支持图标：`dashboard / chat / skills / image / calendar / outputs / text`；未知图标回退为文本图标。
- 设置入口保留在左下角；窄屏移至顶部。该入口始终可访问，不会随通用导航隐藏。
- `modules` 中注册的业务模块自动获得独立入口、表单与任务详情。左上角模式选择器也可切换模块。
- 用 `scripts/create_workbench.py` 创建新项目，自动分配新实例ID；不要复制已有outputs来充当新项目。

## 前端组件边界

| 文件 | 职责 |
| --- | --- |
| `frontend/src/styles/easel-base.css` | 原版调色板、间距、圆角、侧栏、卡片、对话、技能、画廊、设置样式 |
| `frontend/src/styles/easel-theme.css` | 原版夜间主题与切换按钮 |
| `frontend/src/styles/template.css` | 模板的数据接线样式、窄屏布局及必要的可读性修正 |
| `frontend/src/components/WorkbenchShell.tsx` | 侧栏、品牌、导航、会话列表、状态与设置入口 |
| `frontend/src/components/Dashboard.tsx` | 原版工作台布局，展示本实例的真实统计与快捷入口 |
| `frontend/src/components/SettingsDialog.tsx` | 六通道设置弹窗、焦点约束、关闭和配置保存 |
| `frontend/src/App.tsx` | 页面编排、任务事件、权限确认与上下文草稿 |

扩展业务时优先复用 `btn / field / card / page-title / page-subtitle / page-head / page-body / skill-grid` 等共享类。不要再在业务页面另造一套配色、按钮和侧栏。

## 保留与移除

保留：品牌区、模式选择器、导航活动标识、侧栏会话、日夜主题、纸感背景、卡片、欢迎区、消息布局、输入框、附件、技能选择与抽屉、任务记录、生成文件画廊、悬浮设置和六个模型通道。

未移入：社交账号与登录态、平台发布、运营分析、Clipify、画像和原用户数据。原版环境安装面板依赖Easel专属部署流程，没有放置不可用的安装按钮；模板独立安装使用setup.ps1，CLI连接使用设置中的检测功能。

字体沿用原版字体栈和本地回退，不自动请求Google Fonts；不同机器的已安装字体可能影响字形。窄屏改为可横向滚动的导航与紧凑会话栏，以保证设置和输入区可用。

样式与交互验证：`scripts/verify_visual.py`；端到端离线任务验证：`scripts/verify_ui.py`。真实Codex测试需显式执行 `scripts/verify_codex_ui.py`，文件生成模式再加 `--tools`，不会自动批准额外权限。
