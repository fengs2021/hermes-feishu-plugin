# Hermes 飞书插件（增强版 - 支持思维链卡片）

面向 **Hermes** 的飞书 / Lark 通道插件，继承官方 `hermes-feishu-plugin` 全部功能，**额外支持 AI 思维链流式卡片展示**。

## 核心增强：思维链卡片

启用后，飞书上的 AI 对话卡片会：

- **思考中**：显示「💭 思考」折叠面板，展开可见思维链内容
- **回答时**：思维链面板自动折叠（内容保留），正文流式输出
- **完成时**：思维链以折叠状态保留在卡片中

## 安装方式

### 方式一：目录插件安装（推荐）

```bash
# 克隆或更新仓库
git clone https://github.com/fengs2021/hermes-feishu-plugin.git ~/hermes-feishu-plugin

# 安装
cd ~/hermes-feishu-plugin
python3 install.py

# 重启 Hermes Gateway
systemctl restart hermes-gateway
```

`install.py` 会自动：
- 创建插件符号链接（`~/.hermes/plugins/hermes_feishu_plugin` → 仓库目录）
- 写入 `sitecustomize.py` 早期加载器
- 清理旧版遗留文件

### 方式二：作为 Python 包安装

```bash
git clone https://github.com/fengs2021/hermes-feishu-plugin.git
cd hermes-feishu-plugin
pip install -e .
systemctl restart hermes-gateway
```

### 方式三：更新到最新版

```bash
cd ~/hermes-feishu-plugin
git pull
systemctl restart hermes-gateway
```

## 运行配置

| 环境变量 | 值 | 说明 |
|---------|-----|------|
| `HERMES_FEISHU_REPLY_MODE` | `auto`（默认）| 私聊流式，群聊静态 |
| `HERMES_FEISHU_LOCALE` | `auto`（默认）| 自动判断语言 |

### 回复模式

- `auto`：私聊流式卡片，群聊静态卡片
- `streaming`：所有会话流式
- `static`：所有会话静态

## 思维链功能说明

本插件在 Hermes Gateway 运行时注入思维链补丁，无需修改 Hermes 核心代码。注入通过以下链路完成：

```
sitecustomize.py（Python 启动时自动加载）
  → hermes_feishu_plugin.startup
    → apply_runtime_patches()  # 动态注入 stream_consumer 补丁
```

## 原版 vs 增强版差异

| 功能 | 官方原版 | 本增强版 |
|------|---------|---------|
| 流式卡片 | ✅ | ✅ |
| 思维链展示 | ❌ | ✅ |
| 工具执行面板 | ✅ | ✅ |
| Typing 状态 | ✅ | ✅ |
| 消息合并 | ✅ | ✅ |
| 噪音抑制 | ✅ | ✅ |

## 项目结构

```
hermes-feishu-plugin/
├─ plugin.yaml           # Hermes 目录插件元数据
├─ __init__.py           # 目录插件入口
├─ install.py            # 本地安装脚本
├─ pyproject.toml        # Python 包配置
├─ src/hermes_feishu_plugin/
│  ├─ startup.py         # 运行时补丁注入
│  ├─ card/
│  │  ├─ streaming.py    # 流式卡片核心逻辑
│  │  ├─ builder.py      # 卡片构建（含思维链）
│  │  └─ tool_panels.py  # 工具/思维面板
│  └─ channel/
│     └─ runtime_state.py # 运行时状态
```

## 许可证

Apache License 2.0
