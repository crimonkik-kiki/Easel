# Easel 运营分析交付与验收

> 后续状态（2026-10-21）：用户决定不再使用该功能，已撤下工作台入口及 `/api/operations/*` 路由。以下内容为历史实施记录，不代表当前在线功能。历史数据保留不删除，账号管理与发布流程保持现状。

交付日期：2026-10-21。入口：工作台下方「运营分析」。本次把旧版浏览器缓存中的创作数据卡片，扩展为按账号保存的分析、作品复盘和数据管理模块。没有恢复此前撤回的发布队列或重新改造发布流程。

## 功能与使用

1. 按实际账号名选择账号，支持全部账号对比；同平台同名账号用账号标识末尾区分。未添加的平台占位项不计入分析账号数。
2. 选择近 7、30、90、365 天，查看粉丝合计、有效基线净增、区间作品量和指标覆盖情况。
3. 查看粉丝、获赞、作品数快照趋势，以及各账号的实际基线、最后观测时间、来源和过期状态。
4. 在「作品表现」搜索标题或话题，筛选平台，按阅读/播放、点赞、评论或赞评率排序；每页 50 条。
5. 在「复盘与洞察」查看有数据依据的规则结论、各平台话题表现、发文时段分布及同步/导入记录。
6. 选择单个账号后，导入 UTF-8 CSV/JSON，或明确点击「同步此账号」。打开分析、切换账号和刷新报表只读本地数据，不发起账号核验或采集。
7. 下载空白 CSV 模板，导出作品/历史 CSV 或完整报告 JSON。CSV 保留近似值标记，并防止文本被电子表格解释为公式。
8. 原按平台保存的历史保留不动。仅原默认账号显示迁入入口，用户确认归属后才能导入，新增账号不能接收默认账号历史。

## 数据路径与统计规则

数据库：`outputs/_analytics/operations/analytics.sqlite3`，SQLite 事务持久化。

| 数据 | 身份与版本 |
| --- | --- |
| 账号快照 | 独立账号标识 + 观测时间 |
| 作品观测 | 独立账号标识 + 稳定作品 ID + 观测时间 |
| 操作记录 | 账号 + 时间 + 成功/失败/导入状态 |

- 重复导入完全相同的记录不会重复计数；同一身份与时间的数据冲突时整次事务回滚，不静默覆盖。
- 作品优先使用稳定 ID，缺少 ID 时仅接受不含查询参数的 HTTPS 原文链接。共享作品管理页不能作为作品身份。链接去掉认证信息和查询参数，防止把临时凭据带入报表；若作品身份依赖查询参数，必须另外提供 ID，不能把两个作品误合并。
- `observed_at` 是观测时间；`published_at` 是作品发布时间。时间接受秒级 Unix 时间或包含时区的 ISO 时间。拒绝负数、非整数指标、NaN/Infinity、空快照和未来记录。
- 所有缺失指标保留 null，零是真实零。没有区间起点基线或有效期末观测时不计算净增；合计净增要求所有所选账号都有有效基线，显示实际基线日期。
- 趋势每天保留最后一次观测；缺失日期不补零。虚线仅连接实际观测点，不表示连续日数据。
- 作品采用最新一次观测的累计指标，不能相加重复观测；累计表现不等于所选日期范围内的新增流量。
- 缺少发布时间的作品保留在表格，排除在区间发布量、话题和发文时段分析之外。
- 赞评率 =（点赞 + 评论）/ 阅读或播放 × 100%；缺分子、缺分母或分母为零时为空。
- 万/亿等缩写解析为近似数并标记 `approximate`，界面显示 ≈。话题和时段均值仅包括有阅读/播放值的作品。
- 不同平台阅读/播放定义不同；粉丝合计不做人群去重；时间统一 UTC+8。时段、话题与流量的相关性不代表因果。
- 本轮未实现收入归因、外部投放转化、粉丝人群画像或流量预测；这些需要相应来源字段，不能由现有指标推断。

## 来源与取数边界

| 来源值 | 界面说明 | 写入方式 |
| --- | --- | --- |
| manual_import | 人工导入 | 用户选择账号和文件后确认 |
| platform_readback | 平台读回 | 用户明确点击单账号同步，复用现有采集器 |
| legacy_platform_history | 旧版快照（已确认归属） | 用户确认原默认账号历史归属 |

支持既有七个平台的数据适配入口：小红书、抖音、快手、知乎、微信视频号、B站、公众号。适配入口存在不等于本轮实测成功：本轮严格使用模拟账号及隔离数据，没有真实账号登录、真实后台访问或发布，也没有验证平台实时选择器有效性。

平台适配只保存可识别的返回值。未返回的字段保持缺失；没有稳定 ID 的作品跳过并在同步记录中说明。无法取到指标时报告失败，保留上次成功数据，不写零或空成功快照。原始平台指标保留自身统计窗口，不能被误解为当前所选日期范围。

同步调用携带当前账号的 profile 目录。独立账号的采集缓存隔离，不读写旧版平台共享历史。同步期间阻止同账号登录、后台操作、核验、退出和发布；同账号重复同步请求共享一次任务，客户端断开不会取消正在运行的取数任务。本轮没有引入新的代理或浏览器身份参数。

## 导入格式

CSV 首行为字段名，每行 `kind` 为 `snapshot` 或 `work`。单文件最多 5MB，每类最多 5000 行。时间、账号及指标错误会拒绝整次导入。账号由界面选择决定，文件如另带 `account` 字段必须与选择一致。

```json
{
  "snapshots": [
    {"observed_at": "2026-10-20T18:00:00+08:00", "followers": 100}
  ],
  "works": [
    {
      "id": "your-stable-work-id",
      "title": "作品标题",
      "published_at": "2026-10-19T12:00:00+08:00",
      "observed_at": "2026-10-20T18:00:00+08:00",
      "views": 1000, "likes": 20, "comments": 5,
      "topics": ["话题"]
    }
  ]
}
```

上方仅为格式说明，不会注入生产数据库。后台原始导出如果列名不同，需要先映射到模板字段，不能假定任意平台导出可直接导入。

## 实现文件

- `web/operations.py`：存储、验证、聚合、统计口径及导出。
- `web/operations_api.py`：被动读取、主动导入/同步、旧历史归属确认。
- `web/app.py`：注册路由，账号操作互斥，按账号选择采集 profile 与缓存目录。
- `skills/shared/scripts/account_stats.py`、`weixin_mp_stats.py`：分析调用可以禁用旧版平台历史写入。
- `web/frontend/src/components/OperationsAnalytics.tsx`、`styles/operations.css`：完整分析界面。
- `DashboardPage.tsx`、`lib/api.ts`：接入新模块并移除工作台开页自动核验账号的调用。
- `Sidebar.tsx`：导航标签补充可访问名称；分析页窄屏侧栏使用图标，防止挤压内容。
- `tests/test_operations.py`、`test_operations_integration.py`：存储/API/实际应用集成回归。
- `scripts/verify_operations_ui.py`：真实 Edge 内的隔离界面测试，拦截所有外部请求。
- `scripts/prepare_operations_release.py`、`deploy_operations.ps1`、`operations_release_health.py`：回滚副本、空闲检查、隐藏启动和被动健康检查。

## 验收证据

命令：

```powershell
.venv\Scripts\python.exe -m pytest tests/test_operations.py tests/test_operations_integration.py tests/test_web_analytics.py tests/test_account_stats_fetch.py tests/test_account_stats_login.py tests/test_account_whoami.py tests/test_channel_accounts.py tests/test_analytics_transport.py tests/test_mp_login.py -q --basetemp=tmp/ops-tests-deploy
```

实际输出：`169 passed in 2.03s`。覆盖：账号隔离、事务回滚、重复导入、并发同步、异常保留、来源、时间口径、跨账号拒绝、大小限制、旧历史确认及既有登录/取数回归。

```powershell
node --test tests/frontend/accountLogin.test.mjs
```

实际输出：15 tests / 15 pass / 0 fail。前端 TypeScript 类型检查、四个相关文件的 oxlint 检查及候选构建通过。构建仍有单 JS 包超过 500kB 的体积提示，不影响本次功能；未为此扩展到无关架构重构。

```powershell
.venv\Scripts\python.exe scripts/verify_operations_ui.py
```

最终连续三次通过，隔离目录分别为：

- `tmp/operations-ui/isolated-szfc7u8y`
- `tmp/operations-ui/isolated-insvrk1m`
- `tmp/operations-ui/isolated-uujtaret`

每次实际结果：`ui=passed, save_reload=passed, failed_import_preserves_data_and_file=passed, search_export=passed, manual_refresh_only=passed, simulated_collections=2, real_platform_visits=0, production_data_writes=0`。另覆盖同步失败保留、空账号、接口失败、报表恢复以及窄屏底部统计口径展开。

### 视觉验收

沿用 Easel 的浅色/深色、蓝紫色主操作和现有组件风格；主任务是先辨别数据覆盖，再比较作品，最后复盘。没有另造设计系统或加入营销装饰；复用已有按钮反馈，没有新增动画。

独立视觉评审一轮，8.2/10，无阻断问题。评审指出的窄屏按钮换行、深色选中项对比、辅助文字过小均已修正，主 Agent 复看最终截图。辅助说明仅保留影响统计解释的来源、缺失、基线和口径内容；未删必要的指标定义。

最终截图在 `tmp/operations-ui/`：`overview.png`、`works.png`、`insights.png`、`mobile.png`、`mobile-bottom.png`、`dark.png`、`zoom-200.png`、`empty.png`、`error.png`。旧界面基线是 `baseline.png`。已检查 1440 桌面、390 手机、深色和 200% 放大；大表格与图表可横向滚动。

## 部署结果与回滚

发布目录：`tmp/operations-release-20261021-112607`。其中保存候选源码 SHA256、测试版本源码、原 dist 和只撤回本次分析改动的源码副本。已有账号管理和发布改动保留；新数据库不随回滚删除。

部署前未发现账号任务或 Easel profile 浏览器。部署只重启经 executable/父子进程确认属于本项目的 7860 服务；后台启动使用隐藏窗口。

健康检查实际结果 `HEALTHY`：首页包含候选 `index-BdOTMo6N.js`，分析账号接口、分析报告及结构、账号列表、技能列表全部通过，采集/登录请求数为 0。部署成功，未触发回滚。

探针区分 `SERVICE_UNAVAILABLE` / `SERVICE_UNHEALTHY` 与 `PROBE_ERROR_MANUAL_REVIEW`。任何非零结果停止部署并恢复旧源码与 dist，探针异常也不会静默放行。部署脚本不重试发布，需人工检查后才能再次操作。
