# 套用模板做新的工作台

## 1. 修改品牌与端口

`workbench.json` 的 `name`、`logo`、`welcome_title`、`welcome_subtitle`、`navigation`、`port` 控制品牌、欢迎页、导航与启动地址；详见 [框架配置](UI-FRAMEWORK.md)。`id` 用于区分实例；用创建脚本会自动分配新ID。不要仅修改前端标题而保留同一份运行数据。

## 2. 添加一个业务入口

复制 `workbench/modules/brief.py` 为 `customer_reply.py`，声明表单并把输入转换成AI任务：

```python
DESCRIPTOR = {
    'id': 'customer_reply',
    'name': '客户答复',
    'description': '根据客户问题拟定一份供人工审阅的答复。',
    'fields': [{'id': 'question', 'label': '客户问题', 'type': 'textarea'}]
}

def prompt(values):
    question = values.get('question', '').strip()
    if not question:
        raise ValueError('请填写客户问题')
    return '根据以下客户问题起草答复，不杜撰产品承诺：\n' + question
```

在 `workbench.json` 的 `modules` 追加 `workbench.modules.customer_reply` 并重启。侧栏、标准表单、任务持久化、流式输出、失败提示和结果页复用核心代码。模块代码是受信任的服务器扩展，不接受浏览器传来的Python路径或命令。

如果需要专用复杂界面，在 `frontend/src/App.tsx` 拆出自己的页面组件，通过 `/api/jobs` 创建任务，不直接在浏览器保存Key或调用模型服务。

## 3. 接入媒体供应商

`chat / image / transcription / speech / video / music` 六类通道相互独立。协议统一时复用已实现的API合同；协议不同，通过业务模块注册媒体执行函数：

```python
async def generate_video(job, channel, folder, emit):
    # 用channel读取当前实例的base_url/model/key；不要写到日志。
    # 这里按供应商真实协议发起任务、轮询、保存已核对的结果。
    # 限定请求/下载大小、超时、格式和输出目录；不要自动重复提交。
    # 返回相对 outputs/generated 的文件路径数组。
    raise ValueError('请实现并实测供应商协议后启用')

def register(engine):
    engine.media_handlers['video'] = generate_video
```

`register(engine)` 在本实例启动时调用；可用相同方式替换 `image` 或 `speech` 的供应商。执行函数中用 `emit('activity', '当前进度')` 报告进度。供应商已接收请求但结果未知时，保留服务端ID以便人工核对，不能把“查询失败”当作“提交失败”直接重发。

## 4. 接入新的Agent

实现 `workbench.harnesses.base.Adapter`：

- `descriptor`：引擎名称与协议说明。
- `run(request, emit, ask, bind)`：异步执行一轮任务。
- `emit(kind, text)`：统一 token、thinking、activity 事件。
- `ask(questions)`：等待UI确认，必须保留权限选项和原始请求作用域。
- `bind(native_id)`：保存会话归属与原生ID，不擅自替换已有ID。
- 接收协作式取消；回收自己启动的进程，不能按进程名批量杀进程。

将实例注册到 `harnesses/__init__.py` 的 `ADAPTERS`，在 `config.py` 增加支持的引擎ID，并扩展可用性检查。认证由该Agent自己的正规流程完成，不能复制其他项目的登录态来伪装已授权。

## 5. 增加技能

目录结构：`skills/builtin/<id>/SKILL.md`，可附 `references/` 与脚本。前端会自动发现新技能。API模式只注入SKILL.md文本；脚本与参考文件需要原生Agent按规范读取和执行。没有依赖不能标为“可执行”。

导入现有Easel技能时，共享层和可执行依赖需要逐项检查。核心不会自动运行导入脚本，不会默认把账号发布类技能装入新工作台。

## 6. 保持三个边界

1. 业务模块只提交任务或注册适配器；不重写统一的会话、权限与事件机制。
2. 上传原件在 `outputs/_uploads`，交付文件在 `outputs/generated`，配置/数据库/绑定在私有 `_` 目录。下载路由仅暴露生成文件。
3. 新工作台复制的是源码和UI，运行数据与凭据需重新配置。新增业务功能后运行后端测试、前端类型检查、真实入口交互测试，再重新打包。


## v0.2表单与文件约定

业务模块可设置 `action_label` 定义提交按钮；`fields` 支持 `textarea`、`text`、`number`、`select`（`options`为字符串数组）。各模块表单草稿分别保存，任务会记录 `module_id`。模块的prompt函数仍应自行校验输入。

供应商处理器返回的文件必须已存在且位于outputs/generated内，否则任务失败。生成文件页现在递归展示公开交付文件；以点或下划线开头的文件/目录视为内部数据，不对外展示。图片、音频、视频通过受控inline路由预览，其他文件作为附件下载。
