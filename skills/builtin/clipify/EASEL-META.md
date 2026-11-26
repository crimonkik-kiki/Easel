# Easel SKILL 元数据

| 字段 | 值 |
|------|-----|
| **SKILL 名称** | clipify |
| **所属层** | produce |
| **来源仓库** | louisedesadeleer/clipify |
| **GitHub 地址** | https://github.com/louisedesadeleer/clipify |
| **Star 数** | ~100+ |
| **功能描述** | 🔥长视频→社媒短视频：自动找精彩片段+人脸追踪裁切+opus字幕 |
| **SKILL.md 行数** | 167 |
| **文件总数** | 9 |
| **自包含** | 需FFmpeg+Whisper（本地运行，无需云API） |
| **备注** | 167行，直接对应'长视频→短视频'功能 |

> 收录时间: 2026-07-16
> 用途: Easel SKILL 验证测试

## 2026-10-26 中文适配

正式入口：`skills/shared/scripts/clipify.py`；中文内容选段、画幅选择、字幕、任务恢复、内容库预览。实现位于 `easel/clipify*.py`，原始来源信息保留。实测与限制参见 `docs/clipify-adaptation-acceptance-2026-10-26.md`。
