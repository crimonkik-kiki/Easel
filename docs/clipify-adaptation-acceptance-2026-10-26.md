# Clipify 中文适配：首版验收记录

日期：2026-10-26。状态：首版已部署，健康检查通过。发布记录：`tmp/clipify-release-20261026-143846/`。

## 用户入口

刷新工作台，进入“左侧导航栏 → 直播切片”：

1. 粘贴本地视频路径。
2. 选择“保持原比例 / 横屏16:9 / 竖屏9:16”、条数及每条时长。
3. 点击“生成带字幕短片”。可查看阶段进度、取消、恢复和查看历史任务。
4. 播放结果、下载SRT；“校对字幕”允许改文字并生成独立修订版，原成片保留。

默认原比例、3条、20–60秒、清晰中文字幕。首版采用路径输入，没有添加原片上传到内容库的入口。

## 实现位置

- `easel/clipify.py`：任务清单、OS锁、分块转录、全片候选、验证与出片、缓存恢复。
- `easel/clipify_media.py`：FFmpeg定位、PyAV标准元数据接口、PCM读取、取消、精确裁切和比例填充。
- `easel/clipify_captions.py`：真实词时间、中文分句、横竖屏字幕、ASS/SRT、字幕输入转义。
- `skills/shared/scripts/clipify.py`：独立于工作目录的正式CLI入口；`SKILL.md`已更新中文流程。
- `web/clipify_api.py`、`ClipifyPanel.tsx`：工作台入口、任务进度、恢复、字幕修订和预览。
- 共享 `asr.py` 增加可选逐词JSON与PCM兼容路径；默认JSON字段保留。`highlight_cut.py`、`reframe.py`共用媒体工具，原有自检通过。
- `analyze.py`改用真实PTS，`build_pan.py`拒绝空输入/越界。没有把双ROI算法包装成通用人脸追踪。

## 两项方案调整

1. 原计划补齐ffprobe。本机已有PyAV标准接口可准确读取源和成片元数据；实测当前版本的正常 `av.open(path)` 可用。采用该接口作为正式探测实现，明确报告探测后端，避免额外下载二进制。转录改用FFmpeg提取的PCM，绕开faster-whisper与PyAV之间的 `metadata_errors` 参数不兼容；没有降级全局依赖。PyAV已列为直接依赖。
2. 第二阶段旧操作记录接口在用户恢复的工作台中不存在，返回404。旧部署探针因此报“无法核对操作记录”，并非根页面或账号页故障。新探针记录该版本差异，独立检查Windows账号进程、浏览器资料占用、会话锁和切片锁；不把404推断为空闲。部署前检查全部为0。

## 真实素材结果

源：`D:\剪映输出\素材\视屏\20260806_毛毛录屏.mp4`。

正式管线重新完成本地转录，覆盖整片后分成8部分提名，再使用已配置Codex底座全局选择候选；候选必须引用存在的转录段ID，边界由源时间戳计算。

| 验证 | 任务ID | 实际结果 |
| --- | --- | --- |
| 原比例自动全流程 | `clipify-009c9f22d3594542` | 3条，约34.20 / 50.20 / 48.75秒，2560×1440 |
| 显式横屏 | `clipify-0e38fc57a3a4407d` | 1条，2560×1440，复用核验通过的转录 |
| 显式竖屏 | `clipify-fa8b83f9d5fa42d1` | 3条，1080×1920，完整画面居中、模糊填充，复用同一份转录 |
| 字幕修订API到真实渲染 | `clipify-db1d7763a6f44164` | 独立修订任务完成，保留原成片，字幕标注“用户修订字幕” |
| 独立静音片真实ASR | `clipify-2eb24499d0a24f69` | `no_speech`，没有生成空字幕成片 |

第一份 `20261019_100259.mp4` 在这轮回归时已不在原路径，未计作本次正式管线复测通过。静音保护采用明确标记的独立静音样例验证，未冒充原片结果。

所有真实成片经过完整解码、时长、尺寸、音轨和字幕检查。源文件SHA256已在所有真实切片与修订任务之间核对一致；证据：`tmp/clipify-source-integrity.json`。

## 测试命令与结果

以下命令均使用项目 `.venv\Scripts\python.exe` 和项目Node运行时；Windows原生子进程及浏览器测试在正常本机进程环境执行，临时数据隔离。初次沙箱中的测试与原生Codex子进程曾挂起，已按精确命令/PID结束相应测试树，保留转录后恢复，没有结束工作台或其他任务。

```text
python -m pytest tests/test_clipify.py tests/test_clipify_api.py tests/test_clipify_release_health.py tests/test_library_upload.py tests/test_output_paths.py tests/test_output_delete_protect.py tests/test_local_write_guard.py tests/test_direct_api.py tests/test_agent_harnesses.py -q --basetemp=tmp/clipify-pytest-05 --disable-warnings --maxfail=3
224 passed, 6 skipped, 1 warning in 33.13s

python -m pytest tests/test_clipify.py -q --basetemp=tmp/clipify-vfr-pytest-01 --disable-warnings --maxfail=1
43 passed in 5.12s

node --test tests/frontend/*.test.mjs
tests 69 / pass 69 / fail 0

python skills/shared/scripts/highlight_cut.py selftest
selftest 全部通过（energy 定位 + cut 切片 + 转竖版）

python skills/shared/scripts/reframe.py selftest
selftest 全部通过（blur / crop / smart / 显式 size）

python scripts/verify_clipify_ui.py
3 runs passed; external_visits=0
```

第二条媒体测试命令包含新增真实可变帧率片：输出时间间隔保持可变且递增，不强制改成固定帧率。它与前一套测试有重叠，不能把43项再次累加到224项。

6项既有用例因Windows等原有条件跳过，未计为通过。前端全量测试最初有一个旧分析测试从已移除Dashboard提取 `runAna` 而失败；已改为验证分析不会恢复、切片面板必须由用户显式展开，未恢复用户已移除的功能。

TypeScript类型检查及Vite候选构建通过；构建仍有现有大包体积提示，不影响本次运行。`git diff --check`通过（CRLF转换提示除外）。

## 关键验收对照

| 项目 | 结果 |
| --- | --- |
| 中文/空格路径、正式项目入口 | 通过；真实素材与隔离文件均执行 |
| 原比例/横屏/竖屏及字幕重新排版 | 通过；真实横竖视频、三种模式编码与解码测试 |
| 全片选段、真实来源及边界校验 | 通过；8个分块候选及全局排序；拒绝不存在ID、重叠、越界和时长不符 |
| 无音轨/无有效人声/空字幕不冒充成功 | 自动测试与独立静音片通过；原无声录屏本轮缺失 |
| 缓存不串用、源改变/转录改变拒绝复用 | 测试通过；真实横竖切换复用同源转录 |
| 取消/恢复和服务重启后的重复启动保护 | OS锁、单任务标记与恢复测试通过；3轮浏览器交互通过 |
| 字幕修改后生成独立版本 | 接口测试、真实修订任务及3轮浏览器交互通过 |
| 20/25/30/60fps及可变时间间隔ROI | 测试通过；按PTS处理，不再假定30fps |
| 内容库只展示完成的切片项目 | 测试通过；未完成/无声任务的诊断和缓存不作为成片展示 |

## 部署与线上检查

`scripts/deploy_clipify.ps1` 校验候选源码/资源散列，复核空闲后仅重启本项目服务，保留旧哈希资源和源文件备份；失败会回滚并停止，不循环试部署。部署结果 `DEPLOYED`，健康检查 `HEALTHY`。

检查通过：根页面与测试构建、账号页数据、内容库、切片环境、任务列表和详情、运营分析仍保持404。登录/发布请求数为0。

线上无登录资料的Edge只读检查：真实竖屏视频1080×1920，3条可见；所有写请求与账号自动化接口均拦截，实际发生数为0。证据：`tmp/clipify-ui/deployed-result.json`、`deployed.png`。没有真实社媒登录、核验或发布。

## 首版限制

- 自动字幕仍需校对；base模型对同音字、产品名和英文术语可能有误，不能将解码或时间轴通过表述为已逐句听校。
- 自动内容选择沿用已配置且可隔离调用的底座。当前Codex路径实测通过；不支持隔离调用或认证不可用时，保留转录并停在待选段，不擅自换账户/服务。对话可提供选段JSON继续。
- 双ROI和音频对齐工具保留；高级通用人物跟踪、自动理解所有画面的字幕避让未纳入首版UI，也未声称验收通过。
- 竖屏保留完整课件，会缩小原桌面文字；可选择横屏获得更好的课件可读性。


## 左侧导航入口调整

直播切片已独立放到左侧导航栏，内容库移除重复入口；切换页面后可恢复最近任务与画幅选择，打开页面不会自动创建任务。

验证：`node --test tests/frontend/*.test.mjs` 69/69；`tsc -b web/frontend/tsconfig.json` 与 Vite 构建通过；`python scripts/verify_clipify_ui.py --dist tmp/clipify-nav-dist` 3/3（独立导航、高亮、切换页面、取消/恢复、字幕修订、刷新恢复、窄屏，无外部访问）；部署后 `python scripts/clipify_release_health.py --dist tmp/clipify-nav-dist` 返回 HEALTHY。仅更新前端资源，无需重启服务；备份位置见 `tmp/clipify-nav-before-current.txt`。


## 简体中文字幕修复

原因：Whisper 的 zh 语言设置与简体提示不保证文字字形，旧缓存与修订字幕没有交付前转换。新增 OpenCC t2s（本地纯 Python 转换）统一处理词级拼接、段级字幕、人工导入/修订，以及 ASS/SRT 输出；保留原始转录与时间戳。渲染缓存键增加 zh-Hans-t2s-v1 策略，防止复用旧繁体烧录。新进程自动加载修复，无需重启工作台。

测试：`python -m pytest tests/test_clipify.py tests/test_clipify_api.py -q --basetemp=tmp/clipify-simplified-tests-final --disable-warnings --maxfail=2`：66 passed in 9.34s；含三种字幕样式、英文数字保留、旧缓存词级/段级时间不变。依赖：opencc-python-reimplemented 0.1.7，配置 t2s；参考 https://pypi.org/project/opencc-python-reimplemented/ 。

现有成片以独立任务生成简体修订版，不覆盖原视频；映射及逐组完成结果见 tmp/clipify-simplified-repairs.json。修订版保存 zh-Hans 标记，仍明确为未逐句听校。


## 拖拽与点击上传视频素材

左侧直播切片页支持拖拽单个视频、点击选择、进度和取消；上传成功后填入素材路径，再由用户点击生成。上限20GB，支持MP4/MKV/MOV/WebM/AVI/M4V；大文件仍可直接填本地路径。后端4MB分块保存并校验视频画面/音轨，独立UUID目录防同名覆盖，失败清理本次暂存文件；原始素材存放outputs/_clipify_uploads，不进入内容库。上传不会触发转录或账号操作。

验证：`python -m pytest tests/test_clipify_upload.py tests/test_clipify_api.py tests/test_clipify.py tests/test_library_upload.py tests/test_local_write_guard.py -q --basetemp=tmp/clipify-upload-tests-final --disable-warnings --maxfail=2`：101 passed in 6.18s；前端69项通过；TypeScript与Vite构建通过；`python scripts/verify_clipify_ui.py --dist tmp/clipify-upload-dist`隔离浏览器3轮通过（选择、拖拽、错误文件、任务参数衔接、视频加载）。

首次部署因探针httpx继承系统代理，GET /api/outputs误报502而回滚；只读对照trust_env=True返回502、False返回200 JSON数组，证实为探针问题。只修正探针本机直连，未改系统代理。最终部署HEALTHY，真实页面拖拽校验UPLOAD_HEALTHY，上传副本字节哈希一致、未启动处理、素材未进内容库，验收用上传副本已清理。备份与候选快照：tmp/clipify-release-upload-20261026-151916/manifest.json。
