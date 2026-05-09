# 🧠 Hermes Feishu 插件 · 思维链增强版

> 让飞书上的 AI 对话，真正「看得见」思维过程。
> 这是 Hermes Feishu 插件应有的样子。

[![GitHub Repo](https://img.shields.io/badge/GitHub-zirflow/hermes--feishu--plugin--1-blue?logo=github)](https://github.com/zirflow/hermes-feishu-plugin-1)
[![Version](https://img.shields.io/badge/Version-0.6.0-purple?logo=python)](https://pypi.org/project/hermes-feishu-plugin/)
[![License](https://img.shields.io/badge/License-Apache--2.0-green?logo=apache)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11+-orange?logo=python)](pyproject.toml)
[![Status](https://img.shields.io/badge/Status-Production--Ready-brightgreen?logo=vercel)](CHANGELOG.md)

---

## ✨ 思维链 · 重新定义飞书 AI 对话体验

你是否遇到过这些问题？

- ❌ AI 在飞书上回答了，但不知道它是怎么想的
- ❌ 复杂问题触发多轮工具调用，卡片却只显示最终结果，过程全丢失
- ❌ Markdown 表格粘贴到飞书，变成一堆混乱的符号
- ❌ 私聊卡片流式输出看起来很酷，但群聊却只能看到静态消息

**这正是本插件要解决的。**

---

## 🚀 一键安装

```bash
# 推荐：一行命令搞定一切
git clone https://github.com/zirflow/hermes-feishu-plugin-1.git ~/hermes-feishu-plugin && cd ~/hermes-feishu-plugin && python3 install.py && systemctl restart hermes-gateway
```

> 安装脚本自动完成：插件链接 → 运行时注入 → Gateway 补丁 → 多 Profile 同步

---

## 🎯 核心特性

| 特性 | 说明 |
|------|------|
| 🧠 **思维链流式展示** | 折叠面板内实时流式渲染 AI 推理过程，打字机效果，0.3s 节流 |
| 🔄 **多轮卡片生命周期** | 一个卡片贯穿整个 Agent 循环（推理→工具→回答→...→最终），不丢失任何中间状态 |

| 📊 **表格自动转换** | Markdown 表格 → 飞书原生表格，保留格式，无需手动调整 |
| ⚡ **CardKit 流式卡片** | 基于飞书 CardKit 的元素级流式更新，而非全量替换，卡片更稳定 |
| 🔌 **WebSocket 回调** | 支持卡片按钮点击事件回调，实现真正的交互式卡片 |
| 💫 **Burst Merge** | 快速连续消息自动合并，减少刷屏，提升阅读体验 |
| ⌨️ **Typing 指示器** | AI 思考时显示「正在输入...」，体验更自然 |
| 👍 **Reaction 抑制** | 智能过滤重复的 emoji 反应，保持聊天区域整洁 |
| 🩹 **Gateway 补丁** | 自动应用 `reasoning_content` 字段支持补丁，兼容 DeepSeek/MiniMax 等提供商 |

---

## 📖 快速开始

### 环境要求

- Python 3.11+
- Hermes Agent（支持目录插件机制）
- 飞书/Lark 开发者账号（用于配置 Bot）

### 1. 安装插件

```bash
git clone https://github.com/zirflow/hermes-feishu-plugin-1.git ~/hermes-feishu-plugin
cd ~/hermes-feishu-plugin
python3 install.py
```

### 2. 配置飞书 Bot

在飞书开放平台创建应用，启用以下能力：
- **消息 → 接收消息**（使用 ImmessageReceiver）
- **消息 → 发送消息**
- **卡片 → 交互回调**（用于 WebSocket 回调）

获取 `app_id` 和 `app_secret`，配置到 Hermes 环境变量或 `config.yaml`：

```yaml
# ~/.hermes/config.yaml 或项目配置
feishu:
  app_id: "cli_xxxxx"
  app_secret: "xxxxx"
  bot_name: "Hermes"
```

### 3. 重启服务

```bash
systemctl restart hermes-gateway
```

### 4. 验证安装

向 Bot 发送一条消息，观察：
- ✅ 卡片是否正常创建
- ✅ 思维链面板是否展开可见
- ✅ 回复是否流式输出

---

## 💡 功能详解

### 1. 思维链流式展示

当 AI 开始推理时，卡片顶部显示一个 **💭 思考** 折叠面板：

```
┌─────────────────────────────────────────┐
│  💭 思考（展开）                         │
│  ┌─────────────────────────────────────┐ │
│  │ 首先，我需要分析用户的问题...        │ │
│  │ 然后，我需要考虑使用什么工具...      │ │
│  │ 最后，我将给出最终答案。             │ │
│  └─────────────────────────────────────┘ │
│                                         │
│  正在输入答案...                         │
└─────────────────────────────────────────┘
```

**技术实现：**
- 思维文本通过 `reasoning_content` / `thinking_delta` 字段捕获（支持 DeepSeek、MiniMax、Anthropic 等）
- 使用 CardKit `element_id='thinking_text'` 进行元素级流式更新
- 0.3s 节流，防止过快刷新影响体验
- 异常时优雅降级，不阻塞主流程

### 2. 多轮卡片生命周期

复杂问题往往需要多轮 Agent 循环：

```
用户提问 → AI 推理 → 调用工具 → 工具执行 → AI 回答
                ↑                              ↓
                └──────── 下一轮推理 ←←←←←←←←←┘
```

**本插件确保：**
- 同一卡片贯穿整个循环，不重新创建
- 每轮回答累积到 `display_text`，不覆盖
- 工具调用显示在折叠面板内，可展开查看
- 最终答案完成后，所有中间过程保留在卡片中

### 3. Markdown 表格 → 飞书原生表格

输入：
````
| 功能 | 状态 |
|------|------|
| 思维链 | ✅ |
| 流式卡片 | ✅ |
````

输出：自动转换为飞书 `<table>` 元素，保留边框、对齐、样式。

### 5. WebSocket 卡片回调

```python
# 示例：配置回调路由
feishu:
  card_callback:
    ws_endpoint: "wss://your-domain.com/card-callback"
    auth_token: "your-token"
```

卡片按钮配置示例：

```json
{
  "actions": [{
    "tag": "button",
    "text": {"tag": "plain_text", "content": "详情"},
    "method": "callback",
    "callback_id": "show_detail"
  }]
}
```

---

## 🏗️ 架构概览

```
hermes_feishu_plugin/
├── __init__.py                 # 目录插件入口（Hermes 加载点）
├── install.py                  # 安装脚本（插件链接 + Gateway 补丁）
├── plugin.yaml                # 插件元数据
├── pyproject.toml             # Python 包配置
├── patches/
│   └── gateway-reasoning-content.diff  # Gateway 核心补丁
└── src/hermes_feishu_plugin/
    ├── startup.py              # 运行时补丁注入（sitecustomize.py 触发）
    ├── plugin.py                # Hermes 插件接口实现
    ├── card/
    │   ├── builder.py           # 卡片构建器（含思维链面板）
    │   ├── streaming.py         # 流式卡片核心逻辑
    │   ├── tool_panels.py       # 工具面板 + 思维面板流式更新
    │   ├── table_parser.py      # Markdown → 飞书表格转换器
    │   ├── cardkit.py           # CardKit API 封装
    │   ├── heartbeat.py         # 卡片心跳保活
    │   └── models.py            # 数据模型
    └── channel/
        ├── runtime_state.py     # 运行时状态管理
        ├── patches.py           # Hermes Channel 运行时补丁
        ├── ws_callbacks.py      # WebSocket 回调处理器
        ├── typing.py            # Typing 指示器
        ├── reactions.py         # Reaction 抑制
        └── burst_merge.py       # 消息合并
```

**核心数据流：**

```
用户消息
    ↓
Hermes Gateway (应用 Gateway 补丁)
    ↓
hermes_feishu_plugin.startup (注入运行时补丁)
    ↓
AIAgent._fire_reasoning_delta (monkey-patch)
    ↓
_handle_reasoning_delta (线程安全处理器)
    ↓
sync_thinking_card / _stream_thinking_to_card
    ↓
CardKit 流式更新 / IM fallback
    ↓
飞书卡片渲染（思维链展开）
```

---

## 📊 竞品对比

| 功能 | 官方原版 | 本增强版 |
|------|:--------:|:--------:|
| 流式卡片 | ✅ | ✅ |
| 思维链展示 | ❌ | ✅ |
| 思维链流式渲染 | - | ✅ |
| 多轮卡片生命周期 | ❌ | ✅ |
| 中文思维预填 | ❌ | ✅ |
| Markdown 表格转换 | ❌ | ✅ |
| CardKit 元素级更新 | ⚠️ 部分 | ✅ 完整 |
| WebSocket 回调 | ❌ | ✅ |
| Burst Merge | ✅ | ✅ |
| Typing 指示器 | ✅ | ✅ |
| Reaction 抑制 | ✅ | ✅ |
| Gateway 补丁自动应用 | ❌ | ✅ |
| 多 Profile 同步 | ❌ | ✅ |

> **结论**：这不是简单的 Fork，这是飞书 AI 对话体验的重新定义。

---

## 🚢 部署方式

### 方式一：目录插件（推荐）

```bash
git clone https://github.com/zirflow/hermes-feishu-plugin-1.git ~/hermes-feishu-plugin
cd ~/hermes-feishu-plugin
python3 install.py
systemctl restart hermes-gateway
```

**优势**：即插即用，支持多 Profile 自动同步，升级只需 `git pull`

### 方式二：pip 安装

```bash
git clone https://github.com/zirflow/hermes-feishu-plugin-1.git
cd hermes-feishu-plugin
pip install -e .
systemctl restart hermes-gateway
```

**适用场景**：没有目录插件机制的 Hermes 版本

### 方式三：Docker

```dockerfile
FROM python:3.11-slim
RUN pip install hermes-feishu-plugin
# 或从源码构建
COPY --from=builder /app /usr/local/lib/hermes-agent
```

---

## ⚙️ 配置参考

### 完整配置示例

```yaml
# ~/.hermes/config.yaml

hermes_feishu_plugin:
  # 思维链配置
  thinking:
    enabled: true
    expanded: true           # 默认展开思维面板
    streaming: true          # 流式渲染思维内容
    throttle_ms: 300          # 流式节流（毫秒）

  # 回复模式
  reply_mode: "auto"         # auto | streaming | static
  
  # 本地化
  locale: "auto"             # auto | zh_CN | en_US

  # WebSocket 回调
  card_callback:
    enabled: false
    ws_endpoint: "wss://example.com/card-callback"
    auth_token: ""

  # Burst Merge
  burst_merge:
    enabled: true
    threshold_ms: 500         # 超过此时间间隔的消息合并

feishu:
  app_id: "cli_xxxxx"
  app_secret: "xxxxx"
  bot_name: "Hermes"
  api_base: "https://open.feishu.cn"  # 中国区
  # api_base: "https://open.larksuite.com"  # 国际版
```

### 环境变量覆盖

```bash
export HERMES_FEISHU_APP_ID="cli_xxxxx"
export HERMES_FEISHU_APP_SECRET="xxxxx"
export HERMES_FEISHU_REPLY_MODE="auto"
export HERMES_FEISHU_LOCALE="auto"
```

### 思维链面板配置

```yaml
hermes_feishu_plugin:
  thinking:
    panel_title: "💭 思考"   # 面板标题
    collapsed_by_default: false  # 设为 true 则默认折叠
    show_tool_calls: true     # 在思维面板显示工具调用
```

---

## 🔧 故障排查

### 思维链面板为空

**检查项：**
1. Gateway 补丁是否成功应用？
   ```bash
   grep -r "reasoning_content" /usr/local/lib/hermes-agent/gateway/ 2>/dev/null | head -5
   ```

2. 模型是否真正输出 `reasoning_content`？（部分模型使用 XML 标签）

3. 查看日志：
   ```bash
   tail -f /tmp/hermes_*.log 2>/dev/null || journalctl -u hermes-gateway -f
   ```

### 卡片重复创建

**原因**：CardKit 路径失败后的 IM fallback 未在锁内执行

**解决**：已在 0.6.0 修复，升级到最新版即可

### 多轮对话卡片提前闭合

**原因**：`is_final` 逻辑错误

**解决**：已在 0.6.0 修复，升级到最新版即可

---

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

### 开发环境搭建

```bash
# 克隆仓库
git clone https://github.com/zirflow/hermes-feishu-plugin-1.git
cd hermes-feishu-plugin-1

# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -e ".[test]"

# 运行测试
pytest tests/ -v

# 本地安装（开发模式）
python3 install.py
```

### 分支策略

```
main          → 稳定版本
develop       → 开发版本
feature/xxx   → 新功能分支
fix/xxx       → 修复分支
```

### 提交规范

```
feat: 新功能
fix: 修复 bug
docs: 文档更新
refactor: 重构
test: 测试
chore: 构建/工具
```

---

## 📝 更新日志

See [CHANGELOG.md](CHANGELOG.md) for full version history.

### v0.6.0 (最新)

- ✅ 多轮对话卡片生命周期修复
- ✅ 思维面板默认展开
- ✅ 中文思维预填支持
- ✅ CardKit 流式思维渲染
- ✅ Gateway 补丁自动应用

---

## 📜 许可证

Apache License 2.0 - see [LICENSE](LICENSE) for details.

---

## 🙏 致谢

- 原始插件：[hermes-feishu-plugin](https://github.com/fengs2021/hermes-feishu-plugin)
- Hermes Agent 框架
- 飞书 CardKit 团队

---

<p align="center">
  <strong>如果这个项目对你有帮助，请给我们一个 ⭐</strong>
</p>
