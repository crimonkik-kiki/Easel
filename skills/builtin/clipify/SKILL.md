---
name: clipify
description: >-
  中文直播、课程、访谈内容切片：本地转录、全片知识选段、横屏/竖屏/原比例、清晰中文字幕。
  当用户说直播切片、课程剪精华、长视频切短、提取精彩片段、带字幕短片时使用。
  video-highlights 保留音频能量快速找点；本技能侧重有完整语义与来源依据的内容选段。
layer: produce
---

# Clipify：中文直播与课程切片

## 输入与默认值

必需本地视频路径。默认中文、3条、每条20–60秒、清晰中文字幕。
画幅选项：`source`保持原比例、`16:9`横屏、`9:16`竖屏。遵循用户已指定或工作台已显示的设置；未指定保持原比例，不反复询问基础格式。

使用项目 `.venv/Scripts/python.exe`（Windows）或 `.venv/bin/python`，禁止调用其他项目的PATH Python或全局whisper。脚本：`skills/shared/scripts/clipify.py`。

## 正式命令

以下示例相对于项目根；其他工作目录使用绝对脚本路径。

```powershell
# 检查本地环境，不下载模型、不调用AI
& .\.venv\Scripts\python.exe skills\shared\scripts\clipify.py check
# 创建任务，JSON返回id
& .\.venv\Scripts\python.exe skills\shared\scripts\clipify.py create -i "D:\素材\课程.mp4" --aspect source --count 3 --minimum 20 --maximum 60
# 自动转录、当前底座选段、字幕、渲染和核验
& .\.venv\Scripts\python.exe skills\shared\scripts\clipify.py run --job <任务ID>
# 状态、取消、恢复
& .\.venv\Scripts\python.exe skills\shared\scripts\clipify.py status --job <任务ID>
& .\.venv\Scripts\python.exe skills\shared\scripts\clipify.py cancel --job <任务ID>
& .\.venv\Scripts\python.exe skills\shared\scripts\clipify.py resume --job <任务ID>
```

工作台入口：左侧导航栏 → 直播切片。填写路径、选择画幅/数量/时长，可查看进度、取消/恢复、播放成片、下载字幕、校对并生成独立修订版。

## 对话内内容选段

可以由当前对话Agent选段，不强制再开一次模型调用：

1. `create`创建任务；`transcribe --job <任务ID>`只转录，停在`awaiting_selection`。
2. 阅读任务目录的`transcript.json`，覆盖全片；长转录分块提名后全局排序去重。
3. 知识课程按完整观点、步骤、案例找点，娱乐访谈才以笑点为主。不能把大音量当作知识价值。
4. 保存如下JSON清单，数量和时长与任务设置一致，不越界、不重叠、不切断重要限定条件。

```json
{"segments":[{"start":189.6,"end":216.1,"title":"AI工具与智能体","reason":"完整解释两者差异"}]}
```

5. `select --job <任务ID> --segments <JSON路径>`保存选段；`render --job <任务ID>`生成并核验。已取消任务用`resume`。

自动选段复用现有已配置文本API或受支持Agent底座，不接受额外工具权限确认。不支持隔离调用的底座会停在`awaiting_selection`并说明原因，此时可由当前对话选段后导入。不得擅自切换模型账号、收费API，或把能量选段冒充内容判断。

## 产物与可信边界

- 产物位于`outputs/clipify-<ID>/`：任务清单、转录、视频、SRT/ASS、修订记录、验证结果。
- 原视频只读。画幅冻结在本次任务；横竖屏转换保留完整画面，居中填充背景，不裁掉课件/操作界面。
- 原比例保留源尺寸与帧率；字幕按最终画布排版。没有真实词级时间，不能声称逐字精确对齐。
- 无音轨、未检出人声、候选不足、模型或依赖失败均明确报告；空字幕不算成功。
- 自动识别稿未逐句听校。不偷偷改写人物、数字、承诺和观点；提供修订建议、保留版本。
- 技术检查包括全片解码、尺寸、时长、音轨、字幕时间轴，不代替实际内容听校。
- OS锁保护同一任务和重处理资源，取消只作用于本任务。恢复核对源指纹、模型和参数，不能串用缓存。
- 改画幅新建任务，可复用核验通过的转录；已完成成片不覆盖。

## 可选旧工具

`build_ass.py WHISPER.json OUT.ass minimal --width 2560 --height 1440`生成清晰中文ASS；opus/karaoke高亮需要真实词级时间戳。

`analyze.py`读取固定双ROI的真实PTS，`build_pan.py`生成左右硬切表达式。它们不是通用人脸追踪，屏幕演示默认不启用。`audio_align.py`保留音频对齐用途。

不自动发布、不登录社媒平台。
