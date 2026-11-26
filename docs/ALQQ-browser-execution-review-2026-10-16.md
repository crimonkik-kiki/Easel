# ALQQ 登录、发布与浏览器执行层对照审查

审查日期：2026-10-16。对象：本机 D:/ALQQ 安装包与当前 Easel 工作台。方法：静态阅读可见 JS/CJS、运行时清单与调用结构；未执行 ALQQ 模块、未读取浏览器账号资料、未登录或发布真实平台内容。

## 结论

ALQQ 更值得借鉴的是统一执行器、账号互斥、任务与设置快照、提交结果分层及重试约束，而不是照搬页面或猜测浏览器指纹处理。用户观察到的稳定性更好有具体工程设计可以解释；违规风险更低仍不能仅据静态代码和一次成功发布确认。

## 已有直接证据

| 执行层主题 | ALQQ 可见证据 | 工作台现状 | 应采用的设计 |
|---|---|---|---|
| 统一运行时 | engine/package.json 使用 playwright-core；browser-runtime/runtime.json 有独立引擎标识与浏览器版本；浏览器工厂另有模块 | 多个平台 Python 脚本分别启动 Playwright，运行参数及验证方式分散 | 一个 BrowserManager 管理版本、启动、上下文、关闭；平台适配器只处理平台差异 |
| 登录与后台窗口 | sidecar/login.js 有 loginAccount、attemptLogin、openBackend、trackBackendWindow、closeOpenBackends；登录结果含 storageState、identityVerified、identityUserId 字段 | 独立持久化目录已实现，但窗口、进程与身份结果主要依赖多个字典和状态 JSON；真实昵称与固定平台用户 ID 未形成统一身份合同 | 显式启动登录任务；核实账号身份后保存；窗口关闭和资料保存完成后再释放占用；不将网页外壳当作身份已确认 |
| 账号操作锁 | accountOperation.js 包含 accountIdentity、engineAccountId、acquireAccountOperation 与 operations Map；executor 有 withDirectPublishLock | 已有登录进程、校验任务和发布集合的检查，但没有统一且跨服务重启可靠的操作租约 | 登录、校验、打开后台、发布共用同一账号锁；带任务 ID、拥有者、阶段和到期处理；浏览器未关闭不得先解锁 |
| 运行并发 | executor.js 的 concurrencyCeiling 默认返回 1，有显式上限；admissionDecision 每次准入 1 个 | 发布页通常逐个调用，但其他页面校验和后台窗口可同时活动；不存在全局准入器 | 全局执行队列与资源上限，加同账号互斥；这是防资源竞争和资料损坏，不是模拟真人策略 |
| 发布设置冻结 | shared/publishSettingsSnapshot.cjs 的 assertSnapshot 核验版本、平台和内容类型；buildFrozenPayload 生成账号独立提交数据；注释明确不可用后来修改的预设回填遗漏字段 | 账号话题和尾注在请求到达时读取；前端确认与实际请求之间，其他页面仍可能修改预设 | 发布前生成每账号实际提交快照，确认后不再重新取文案或预设；网络和认证单独解析 |
| 已提交与结果不明 | shared/publishRetryPolicy.cjs 明确区分 submitted、reviewing、submitted_unknown、published、draft、rejected 等；提交不明时返回 inspect，canRetry=false、automaticRetry=false | 部分平台脚本内部有核验；但 Web 汇总仍主要判断 returncode == 0，UI 多为发布中/成功/失败 | Web 与脚本共享结构化状态；阶段和是否已提交必须独立记录；提交后超时进入待确认，不自动重新提交 |
| 重试边界 | 同一重试策略供 API、调度、worker 和 UI 使用；拒稿要求改稿；不明结果要求核对；参数问题要求修改 | 错误多表现为日志尾部/字符串；不同执行路径的处理尚未形成统一策略 | 错误码、阶段、可重试性和用户下一步统一；重新查询任务结果与重新提交内容必须分开 |
| 结果回传 | completionOutbox.js 有 createCompletionOutbox、scopeKey、sameScope、safeOutcome；executor 引用 outbox；safeOutcome 过滤敏感字段并限制结果大小 | 主要是进程输出、少量状态 JSON、发布日志及日历记录 | 本地持久化任务和结果发件箱；保存成功结果后再回报 UI；回报失败不能导致再次发布 |
| 本地素材 | localVideoFile.js 明确验证本地原生路径、实际文件、读取权限、私密路径；prepareLocalVideoData 同时处理封面 | 浏览器文件选择后复制到本机 _publish/media，已限制目录和文件大小；还没有原生文件选择和统一封面合同 | 保留安全复制路径；如果增加桌面原生选文件，采用受控文件引用与明确授权，不开放任意路径读取 |

## 不能从当前审查确认的事项

- browserFactory.jsc、browserContext.jsc、publishingBrowserRuntime.jsc、loginVerificationPolicy.jsc、shipinhaoSession.jsc 等属于编译文件，当前未还原内部实现。
- 尚不能确认每个平台实际采用持久化用户目录、storageState 恢复，还是混合策略；只看到统一接口及部分返回字段。
- 不能从这些文件证明 ALQQ 获得各平台自动登录、自动浏览、自动发布授权。
- 不能把独立浏览器版本、代理设置等同于更低违规概率；不提出隐匿自动化、规避检测的实现。
- ALQQ 是否自动进行后台登录态核验，以及具体核验频率，本次没有足够直接证据。不能宣称它一定没有后台访问。

## 工作台应优先改造的顺序与验收

1. 真实账号访问改为显式任务。默认页面仅读缓存；测试全用模拟账号。验收：进入账号管理/发布页不启动平台浏览器，也不请求平台身份接口。缓存状态标明最近核验时间。
2. 统一 BrowserManager 与账号锁。验收：同账号登录、打开后台、核验和发布互斥；服务重启后可以发现未关闭浏览器，不能简单丢失锁后再启动第二个上下文。
3. 所有发布都进入持久化任务队列。验收：刷新页面保留阶段、目标账号和日志；同一任务不会被重复执行；任务 ID 和请求幂等键可查。
4. 确认页冻结每账号提交参数。验收：确认页展示的标题、正文、标签、尾注、封面和声明与执行数据一致；后续改预设不影响已确认任务。
5. 统一平台回执与重试策略。验收：点提交后断网、页面跳转、验证码、审核中、拒稿及未确认均有明确状态；提交后的未知状态不能自动原样重试。
6. 再完善封面、参数、人工交接和授权接入。按平台支持能力开放，不显示无实际作用的选项。

对小红书：先采用本地创作与人工发布交接。若后续有明确的官方授权范围，再把相应自动执行能力接入；稳定性架构改造仍可用于任务准备、审核、素材管理与结果人工确认。

## 主要证据文件

- D:/ALQQ/engine/package.json
- D:/ALQQ/browser-runtime/runtime.json
- D:/ALQQ/engine/v2/sidecar/login.js
- D:/ALQQ/engine/v2/sidecar/accountOperation.js
- D:/ALQQ/engine/v2/sidecar/executor.js
- D:/ALQQ/engine/v2/sidecar/completionOutbox.js
- D:/ALQQ/engine/v2/sidecar/localVideoFile.js
- D:/ALQQ/engine/shared/publishRetryPolicy.cjs
- D:/ALQQ/engine/shared/publishSettingsSnapshot.cjs
- D:/Codexspace/Easel/web/app.py
- D:/Codexspace/Easel/web/frontend/src/components/AccountsPage.tsx
- D:/Codexspace/Easel/web/frontend/src/components/PublishPage.tsx

此文档是审查结果与改造验收标准，尚未表示上述 BrowserManager、持久化队列或平台回执改造已经实施。
