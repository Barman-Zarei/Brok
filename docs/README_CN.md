[EN](../README.md) | [FA](README_FA.md) | [RU](README_RU.md) | [CN](README_CN.md) | [ID](README_ID.md) | [KO](README_KO.md)

## Brok 🤖 — 桌面 AI 伙伴与编程智能体（波斯语优先）

<img src="brok.gif" width="140" alt="Brok"/>

Brok 是住在你桌面上的小机器人（无边框、始终置顶、可拖动）。它以**波斯语**为首选语言（也支持其他语言），并可作为**带权限控制的编程智能体**处理你的项目。本项目基于 [myCat](https://github.com/yumiaura/myCat)，请参见 NOTICE 与 LICENSE.txt。

- 机器人形象，共 13 种状态（待机、聆听、思考、输入、编码、说话、开心、困惑、错误、成功、睡眠、通知…）
- 可与 **Claude**、**Ollama（本地）** 或任何兼容 OpenAI 的 API 对话；界面始终显示 LOCAL AI / CLOUD AI 标签
- **编码工作区**（右键 → Coding Workspace…）：文件、编辑器、聊天、diff 查看、终端、问题、git。选中代码后可：解释 / 找 bug / 优化 / 写测试 / 转换为 Flutter
- **安全：** 每个工具都有风险等级；修改文件前先显示 diff；删除、commit、push 和高风险命令始终需要确认；危险命令会被直接拦截；步数、时间、token 和工具调用次数均有上限
- 波斯语界面与 RTL、学习模式、AI 调试器、项目健康报告、可控的记忆（`/remember`、`/memory`、`/forget`）、仅本地模式、全局热键（默认 Ctrl+Space）、图片与截图附件

### 安装（Python ≥ 3.10）
```bash
pip install .
brok                              # desktop
export ANTHROPIC_API_KEY=...      # Claude (optional) / Ollama: ollama pull llama3.1
brok-agent doctor
brok-agent --project . ask "..."
```
详情：docs/configuration.md · docs/security.md · docs/coding-agent.md

> 实际状态：核心功能有自动化测试（Python 3.8 与 3.12，Linux，无显示环境）。作者尚未验证：使用真实密钥调用 Claude/OpenAI/GitHub、Windows/macOS 构建、麦克风语音识别。
