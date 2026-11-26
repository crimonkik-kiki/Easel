# ALQQ 发布流程对齐规格（第三阶段基准）

> 来源：对 `D:\ALQQ`（已安装的 ALQQ 桌面版，engine v2.0.0）做的静态勘察。
> 目的：把「ALQQ 能做到的发布自动化流程」变成 Easel 可执行的规格，替代第二阶段遗留的「人工交接」。
> 日期：2026-10-16

---

## 1. 结论先行

**ALQQ 的发布自动化 = Playwright 驱动真实浏览器，操作各平台创作者后台。不是开放 API。**

| 维度 | ALQQ 的做法 |
|---|---|
| 浏览器 | `playwright-core` 1.63.0 + **自带 Chrome 152**（`browser-runtime/browser/chrome.exe`），非 playwright 自带 chromium |
| 登录态 | 持久化 profile（`browser-runtime/profiles/`），每账号一份 |
| 发布方式 | 打开平台创作者后台 → 上传素材 → 填标题/正文/话题 → 设定封面与声明 → 提交 → **读回管理页对账** |
| 平台数 | 24 个平台 × 3 类内容（article / video / dynamic） |
| 适配器契约 | 每平台目录含 `ArticlePublisher` / `VideoPublisher` / `DynamicPublisher` + `auth` + `config` + `index` |
| 登录契约 | 每平台一个 adapter，导出 `extractUsername` / `detectLoginSuccess` / `extractIdentity` |
| 设置规格 | `shared/publish-settings.catalog.json` — 全平台 181 个发布字段（key/type/options/maxLength） |
| 平台清单 | `shared/platformManifest.json` — 24 平台的 supports / requiresCover / 标题上限 / 登录·后台·管理 URL / 成功失败 URL 特征 |
| 声明编目 | 同上 catalog 的 `declarations` — 10 个平台的声明选项清单 |
| 回执与诊断 | `platformFeedback` / `publishDiagnostics` / `publishFailureHint` / `accountRestrictionPolicy` / `adaptiveScheduler` |

**这条路线与 Easel 现有代码是同一条路线**（见 §4），不是两条路。

---

## 2. 平台能力矩阵（24 平台）

| id | 名称 | 内容类型 | 需封面 | 标题上限 |
|---|---|---|---|---|
| baijiahao | 百家号 | article·video·dynamic | 是 | 30 |
| toutiao | 今日头条 | article·video·dynamic | 是 | 30 |
| wechat | 微信公众号 | article·dynamic | 是 | 64 |
| qiehao | 企鹅号 | article·video | 是 | 30 |
| douyin | 抖音 | article·video·dynamic | 是 | 30 |
| bilibili | 哔哩哔哩 | article·video | 是 | 50 |
| kuaishou | 快手 | article·video | 否 | 100 |
| shipinhao | 视频号 | article·video | 否 | 100 |
| guanghe | 淘宝光合 | article·video | 是 | 30 |
| sohu | 搜狐号 | article·video·dynamic | 是 | 30 |
| zhihu | 知乎 | article·video | 否 | 100 |
| xiaohongshu | 小红书 | article·video | 是 | 20 |
| dayu | 大鱼号 | article·video | 是 | 30 |
| kuaichuan | 快传号 | article·video | 是 | 30 |
| weibo | 微博 | article·video·dynamic | 否 | 140 |
| youtube | YouTube | video | 否 | 100 |
| tiktok | TikTok | video | 否 | 150 |
| instagram | Instagram | article·video | 是 | 2200 |
| facebook | Facebook | article·video | 否 | 5000 |
| douban | 豆瓣 | article | 否 | 70 |
| csdn | CSDN | article·video | 否 | 100 |
| jianshu | 简书 | article | 否 | 80 |
| pbootcms | PbootCMS 站点 | article | 否 | 100 |
| innoshop | InnoShop 站点 | article | 否 | 255 |

**对 Easel 的直接价值**：这张矩阵可替代第二阶段自己推导的 `platform-publish-capabilities-2026-10-16.md`，作为平台能力的参照基准（需逐项实测确认，不要直接当结论）。

### 平台 URL 与判定特征（每平台 4 项）

manifest 每平台还带：
- `loginUrl`（登录页）、`dashboardUrl`（后台首页）、`manageUrl`（作品管理页，用于读回对账）
- `successPattern` / `failPattern`：正则，用于判定"还在后台"还是"被踢回登录"

这三个 URL + 两个正则，正好是 Easel 读回对账所需的全部锚点。

---

## 3. 发布设置字段规格（181 字段）

### 3.1 结构

```
platforms.<id>.contentTypes.<article|video|dynamic>.fields[] = {
    key, label, type, maxLength?, options?[]
}
```
`type` 取值：`text` / `textarea` / `number` / `select` / `tags` / `boolean`；
`select` 的 `options` 是 `{value,label}` 或纯字符串数组。

### 3.2 封面机制 —— 这是第二阶段卡住的点，答案在这里

**ALQQ 不在平台侧冻结封面，而是在任务侧冻结「封面来源」。**

抖音的字段定义（article）：
```
douyinCoverMode  select  选项：上传封面图 / AI 配图
```

含义：
- `上传封面图` = 用我方提供的图作为封面
- `AI 配图` = 交给平台生成

所以「抖音封面无法在发布前确定」这个判断本身没错，但**闭环并不需要平台侧能冻结封面**：

> 把「封面来源」连同其余全部设置一起冻结进任务快照 → 发布时按快照执行 → 平台侧实际结果读回对账记录。

这正是 Easel 第二阶段 `publish_snapshot.py` 已经建立的机制。**缺的不是封面合同，是快照与真实执行器的接线。**

抖音视频字段里对应的还有：`topics`(tags,上限20) / `visibility` / `savePermission` / `selfDeclaration` / `location` / `syncToutiao` / `description`(上限500)。

### 3.3 声明合同（`declarations`，10 平台）

三种形态：

| 形态 | 平台 | 样例 |
|---|---|---|
| `sourceDeclarations[]` ({value,label}) | wechat 等 | 内容由AI生成 / 素材来源官方媒体·网络新闻 / 内容剧情演绎，仅供娱乐 / 个人观点，仅供参考 / 健康医疗分享，仅供参考 / 投资观点，仅供参考 / 无需声明 |
| `required[]` + `textSupplementary[]` + `videoSupplementary[]` | sohu 等 | 必选：无需声明·含有虚构演绎内容·含有AI生成内容·含有营销信息·内容为转载·内容为个人观点；补充：引用声明 / 自行拍摄 |
| `sources[]`（纯字符串） | dayu 等 | 无需标注 / AI生成 / 虚构演绎 / 营销信息 / 转载 / 个人观点 / 不适宜未成年人 |

抖音的自主声明选项（6 项）：内容由AI生成 / 内容为个人观点或见解 / 内容为转载信息 / 内容含营销推广信息 / 虚构演绎，仅供娱乐 / 无需添加自主声明。

**对 Easel 的价值**：声明的枚举值是平台 UI 上真实存在的文本，可直接作为选择器锚点，不必再靠猜。AIGC 标识是监管要求，这一项必须落进快照并在发布时真实勾选。

### 3.4 accountConfigKeys（账号级默认值）

manifest 给每个平台列了「账号级默认设置键」，例如抖音有：

```
author, douyinVisibility, douyinSavePermission, douyinSelfDeclaration,
douyinTopicSource, douyinTopics, douyinLocation, douyinCoverMode,
douyinMusicMode, douyinMusicKeywords, douyinMusicAvoidDays, douyinPublishTiming
```

这是「账号预设」的字段清单 —— 对应 Easel 的账号配置页。第二阶段第 4 项「确认后冻结参数，后续改预设不影响已确认任务」的字段集合，就以这份清单为准。

---

## 4. Easel 现状：能力其实已经在

| 资产 | 规模 | 说明 |
|---|---|---|
| `skills/shared/scripts/douyin_publish.py` | 1555 行 | 抖音真实发布器（Playwright）。含：高清发布入口 → 切 tab → 塞 file input → 等上传完成 → **等 AI 封面并选推荐封面** → 填标题/简介 → 提交 → **读回创作者中心作品列表对账**（标题+时间窗匹配才算成功）；扫码登录抠图轮询 |
| `skills/shared/scripts/web_publisher.py` | 1800 行 | **配置驱动通用发布引擎**，面向「无开放 API、只能网页操作」的平台（快手/视频号/知乎等）；子命令 platforms/plan/check/login/publish/selftest；已接入读回对账 |
| `skills/shared/scripts/account_browser.py` | 38 行 | 打开账号现有 profile 到创作者后台（小红书/抖音/快手/视频号/知乎 URL 已内置） |
| 发布类技能 | 13 个 | skill-cross-platform-publish / skill-douyin-upload / skill-xhs-publisher / skill-zhihu-publisher / skill-wechat-publisher / skill-publish-scheduler / skill-publish-log / skill-publish-checklist / skill-publish-analytics / skill-publish-notify … |
| Playwright 内核 | 已安装 | `%LOCALAPPDATA%\ms-playwright\chromium-1228` + `chromium_headless_shell-1228`，Easel venv 内 playwright 可用 |
| 第二阶段基础设施 | 已完成 | 账号锁（browser_manager）、持久化队列（publish_queue）、快照（publish_snapshot）、回执（publish_receipts） |

**所以第二阶段「七个平台全部落到人工交接」的原因不是做不到，而是：**
1. 「可全自动闭环」的判定标准被定在「平台侧可证明冻结」（过严），而 ALQQ 的标准是「任务侧冻结 + 读回对账」（可行）；
2. 已有的发布脚本**没有被实测验证到跑通**，因此被判为不可采信；
3. 快照 / 队列与真实执行器之间缺接线。

---

## 5. 要补的三件事（第三阶段）

| # | 任务 | 验收 |
|---|---|---|
| 1 | **实测验证已有发布器** | `douyin_publish.py` / `web_publisher.py` 在 Windows + 已装 chromium 下，用模拟素材跑通「准备→提交→读回对账」全链路；逐平台记录选择器有效性，失效的标注并修复 |
| 2 | **补齐设置合同** | 以本规格 §3 的字段结构建立平台设置 schema（封面来源、声明枚举、可见性、话题、标题上限等），支持账号预设与任务快照 |
| 3 | **接线闭环** | 队列任务 → 快照冻结设置 → 调用发布器执行 → 读回对账 → 回执落库；把「待人工确认封面」这类中间态替换为平台真实可达的状态 |

优先级：1 → 3 → 2（先证明能发，再谈设置完备）。

---

## 6. 明确不做（边界）

勘察中发现 ALQQ 的 `browser-runtime/profiles/default.json` 是**浏览器指纹伪装配置**：

- 时区伪装 `Europe/Warsaw`、语言 `pl-PL`、`icu_locale pl-PL`、`accept_language pl-PL,pl;q=0.9,…`
- GPU 伪造 `win-rtx4060`、WebGL vendor/renderer 改写
- 硬件参数伪造：`hardware_concurrency 32`、`device_memory 16`、屏幕 2048×1280、DPR 1.25
- `client_hints` 全套改写（brand / platform_version / grease 等）
- 配套 `proxyManager`（89KB，代理池管理）

**这属于规避平台设备识别与多账号防关联，不是「发布自动化流程」。本项目不复刻，也不做等价替代。**

理由：

1. **对国内平台是异常信号，不是隐身。** 账号在国内平台，浏览器声明时区华沙、语言波兰语，再叠加代理 IP 登录创作者后台 —— 这在风控模型里是权重很高的「环境异常 / 异地登录」特征，等于主动显形。
2. **风险收益不成比例。** 单账号或少量账号正常发布，本来就不需要指纹伪装；而一旦被判定为批量分发工具，代价是降权 / 限流 / 封号，尤其对带真实身份与人设的 IP 账号不可逆。
3. **合规边界。** 伪装设备指纹以绕过平台识别，属于规避技术措施，与「用浏览器自动化替代手工点击」是两件事。

ALQQ 发布流程的**主体**（登录 → 上传 → 填字段 → 设封面与声明 → 提交 → 读回对账）本身是正常浏览器自动化，与 Easel 现有路线一致，本规格全部覆盖。被排除的只是指纹与代理防关联层。

---

## 7. 平台适配契约与任务状态机（接口层基准）

以下接口设计来自本工作区既有方案 `D:\workbuddy工作空间\多平台分发工作台\ALQQ复刻实施方案.md` §5.1 / §5.4，已做过独立评审。Easel 现有散装发布脚本（douyin_publish.py / web_publisher.py）应按此契约收敛为统一平台适配层，Python 侧保持同构。

### 7.1 统一适配器契约

```ts
interface PlatformAdapter {
  capabilities: PlatformCapabilities;
  checkAccount(ctx: AccountContext): Promise<AccountCheck>;
  prepare(input: ContentSnapshot): Promise<PlatformPayload>;
  saveDraft(ctx: RunContext, payload: PlatformPayload): Promise<Receipt>;
  submit?(ctx: RunContext, payload: PlatformPayload): Promise<Receipt>;
  verify(ctx: RunContext, receipt: Receipt): Promise<VerificationResult>;
}
```

`RunContext` 传入账号、任务、取消信号、日志、截止时间、**适配器版本**。

### 7.2 任务状态机

```
queued → prechecking → preparing → executing → verifying
                   ↘ waiting_user                ↘ completed
                                                 ↘ submitted
                                                 ↘ uncertain
任意可终止阶段 → failed / cancelled
```

**任务状态与远端内容状态必须分开存**：

| 层 | 取值 |
|---|---|
| 本地任务 | queued / prechecking / preparing / executing / verifying / waiting_user / completed / submitted / uncertain / failed / cancelled |
| 远端内容 | draft / pending_review / published / rejected / unknown |

审核中既不是失败，也不是公开发布成功。

### 7.3 关键约束（都有来历，别丢）

1. **快照冻结**：已入队任务引用固定快照，事后改稿不影响在途内容。（第二阶段 `publish_snapshot.py` 已实现）
2. **不确定态**：提交按钮点击后断网 / 进程崩溃 / 回执丢失 → 标记 `uncertain`，先查后台记录；歧义未消除时交用户确认，**绝不盲目再发**。（第二阶段 `publish_receipts.py` 已实现）
3. **幂等键** = 账号 + 内容快照 + 平台 + 操作，配唯一约束。它只能防本地重复执行；远端无幂等接口时，靠回访与 `uncertain` 处理。
4. **定位策略**：优先语义定位（role / label / 稳定属性），CSS 作后备。**未知页面结构立即暂停，禁止靠页面上「发布」二字猜最终按钮。**
5. **人工接管**：登录失效 / 验证码 / 平台二次确认 → 暂停并打开有头浏览器，接管后**重新核验账号与页面**再恢复执行，不要接着盲跑。
6. **低并发**：全局同时执行数默认 1（试运行上限 2）。同账号串行。

### 7.4 与 ALQQ 规格的对应关系

| ALQQ | Easel 侧落点 |
|---|---|
| 每平台 `ArticlePublisher`/`VideoPublisher`/`DynamicPublisher` | 适配器契约按内容类型分方法实现 |
| `loginAdapters`（extractUsername / detectLoginSuccess / extractIdentity） | `checkAccount()` |
| `publish-settings.catalog.json` 字段定义 | `capabilities` + 平台设置 Schema |
| `platformManifest.json` 的 manageUrl / successPattern / failPattern | `verify()` 的读回锚点 |
| `platformFeedback` / `publishDiagnostics` | `Receipt` / `VerificationResult` / 回执落库 |
