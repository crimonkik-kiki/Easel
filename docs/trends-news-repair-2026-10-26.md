# 热榜与资讯运行环境修复

日期：2026-10-26，时区 UTC+8。

## 根因与修复

1. 热点雷达固定请求 15 条，后端硬上限为 30 条，实际公开源可返回 30～52 条。现在雷达请求最多 100 条，返回 `total` 与实际显示数量。
2. 热榜解析遗漏 `hot_value_desc` 等字段，抖音主源没有原文链接，B站主源只有热词。补齐解析与安全链接处理；缺链接时生成带明确「热词搜索」标记的公开搜索链接，不冒充原文，不生成不存在的热度。
3. 原聚合串行调用六个平台，慢源会拖住整体。改为并发、同平台请求共享任务；单源异常不丢掉其他平台；主源结果过短时尝试备用源，使用较长的有效榜单。失败重试间隔 30 秒，正常缓存 5 分钟。
4. 过期缓存原先没有区分来源时间。现在返回实际成功获取时间与 `stale`，界面显示缓存提示，不能把旧数据当成刚更新。
5. 项目 `.venv` 缺少 `bs4`，依赖清单也没有 `beautifulsoup4`；全局 `python` 属于 Hermes 环境，`python3` 在本机无法执行。已把依赖写入项目清单，并安装在 Easel 自己的 `.venv`，没有修改系统或 Hermes Python。
6. 新增 `scripts/news.ps1`，始终调用本项目解释器，支持 Windows PowerShell 5.1 与当前 PowerShell。资讯技能示例改用此启动器。
7. 原技能示例 `--source rss` 没有对应实现，会静默返回空列表；现支持全部 RSS 源分组，未知源与非法数量明确报错。修正不存在的简报 profile 示例，`--no-save` 不再创建输出目录。

## 使用

```powershell
.\scripts\news.ps1 check
.\scripts\news.ps1 fetch --source 'sspai,infoq_cn' --limit 10 --no-save
.\scripts\news.ps1 fetch --source rss --limit 10 --keyword AI --no-save
.\scripts\news.ps1 briefing --profile tech_digital --no-save
```

诊断实际解释器：`D:\Codexspace\Easel\.venv\Scripts\python.exe`；requests 2.34.2，beautifulsoup4 4.15.0。没有重新创建虚拟环境或重装整个项目。

## 实测

实际运行中的 `/api/trends?platforms=weibo,douyin,zhihu,bilibili,baidu,toutiao&limit=100`，2.91 秒完成，六平台全部成功且非过期缓存：

| 平台 | 返回条数 | 数据边界 |
| --- | ---: | --- |
| 微博 | 52 | 原链接与热度 |
| 抖音 | 50 | 主源未给链接，明确提供热词搜索 |
| 知乎 | 30 | 上游只有 30 条，不补造 |
| B站 | 50 | 上游只给热词，无热度；搜索链接已标记 |
| 百度 | 51 | 原链接与热度 |
| 头条 | 50 | 原链接与热度 |

资讯启动器真实读取少数派 3 条、InfoQ 中文 3 条，结果保存在 `tmp/trends-news-20261026/news-live.json`，没有生成正式简报。人人都是产品经理源返回 HTTP 403，仍不可用，不能归咎于 Python 环境，也没有绕过访问限制。本轮没有声称其余全部资讯源均已实测。

备用源实测有 B站超时、部分 60s 端点 HTTP 429 的情况；本次六平台结果来自可用主源。备用服务的实时可用性不作保证，不会把失败说成没有热点。

## 检查与部署

```powershell
.venv\Scripts\python.exe -m pytest tests/test_trends.py tests/test_news_scripts.py tests/test_web_analytics.py tests/test_operations_integration.py tests/test_account_whoami.py tests/test_channel_accounts.py -q --basetemp=tmp/trends-news-release-tests
```

实际结果：`93 passed in 2.56s`。覆盖格式兼容、52 条不截断、并发去重与顺序、异常隔离、过期缓存、重试间隔、搜索链接、无效源参数、项目解释器选择、PowerShell 单参数转发和 no-save 行为。

前端 TypeScript、目标文件 oxlint 及构建通过。现有单 JS 包超过 500kB 的提示仍存在，未为此修改无关架构。

已部署目录：`tmp/operations-release-trends-news-20261026-104035`，保存修复前 7 个已有文件及 dist，包含候选 SHA256。服务健康检查通过，线上前端 `index-C3rUiEYo.js`；运营分析路由仍为 404，没有恢复已撤下功能，没有登录或发布。

证据：`tmp/trends-news-20261026/trends-live.json`、`deployed-health.json`、`news-live.json`。当前热榜已预热进服务内存缓存，刷新页面即可。
