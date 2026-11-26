# 模板验收说明 · v0.3.0

验收日期：2026-10-27；Windows / Python 3.12 / Node.js 24.22.0 / Edge。

详细问题、复测方法和测试边界见 [复查验收](REVIEW-v0.3.0.md)。

| 验收项 | 证据 | 结论 |
| --- | --- | --- |
| 后端回归与新增用例 | evidence/backend-results-v03.txt | 31 passed |
| 独立目录UI流程 | evidence/ui-results.json | 3/3通过；API/ACP使用本机模拟服务 |
| 真实Codex认证、对话、刷新续接 | evidence/codex-real-ui.json | 通过；只读，无额外权限批准 |
| 真实Codex创建文件与产物读取 | evidence/codex-tools-ui.json | 通过；隔离工作区写入，无额外权限批准 |
| 全新安装、中文空格目录、重复启动、跨目录拒绝与停止（v0.2启动机制，未变更） | evidence/install-results.json | 通过 |
| Easel外观与六通道设置、日夜主题、技能抽屉、内容库画廊 | evidence/visual-results-v03.json | 通过；隔离数据，无AI任务 |
| 最终ZIP内容与解压启动 | evidence/release-results.json | 见最终打包核验结果 |

未复制原项目密钥、登录态、会话或用户素材。原Easel 7860服务未修改。模拟服务产生的图片/语音不代表真实供应商兼容性；真实Codex测试截图有独立文件名。

附114项技能目录，内置3个完整通用技能；其余需按需导入完整技能及依赖。视频/音乐需要注册实际供应商适配器，未接入时明确禁用。

WorkBuddy需要正规OAuth授权与在线桌面客户端，本轮未实测真实账户；OpenCode仅模拟协议验证；Codex原生生图未调用真实生成。其他机器仍需自行安装并认证CLI。macOS/Linux未进行实机验证。

框架面向本机单用户。公网、多用户部署需要另行补充身份认证、访问控制与部署运维。
