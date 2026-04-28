# 更新日志

## [未发布] - 2026-04-29

### 多轮对话卡片生命周期修复

**问题**：复杂问题触发多轮 agent 循环（推理→工具→回答→推理→工具→回答）时，卡片在第一轮回答后就闭合，后续轮次的内容全部丢失。

**修复**：

- **`display_text` 累积** — 多轮回答不再覆盖已有文本，新段落检测到与已有内容不连续时用 `\n\n` 接续
- **`is_final` 逻辑修正** — 只有 gateway 显式传 `finalize=True` 时才真正闭合卡片，`cursor_is_final` 仅触发视觉更新
- **`_finalize_card` 心跳停止** — 完成时取消 heartbeat 任务，防止用 loading 状态卡覆盖已完成卡
- **`_finalize_card` 总是设置 `phase=completed`** — 完成后标记为已完成，阻止新消息 abort 覆盖已完成卡片
- **`wrapped_send_or_edit` 重新激活** — 同一 agent 循环中新轮次到达时，将 `phase` 从 `completed` 重置为 `streaming`
- **`sync_progress_card` 添加 phase 守卫** — 防止完成后被进度更新覆盖

### 思维面板优化

- **`sync_thinking_card` 改用 `stream_card_content`** — 思维面板内容现在通过 CardKit 元素级流式更新，替代全量卡片替换
- **思维面板默认展开** — `tool_panels.py` 和 `builder.py` 中 `expanded: True`，推理时无需手动展开即可看到思考内容
- **`_handle_reasoning_delta` 异常处理** — 去掉静默 `except Exception: pass`，改为 `logger.warning` 带完整堆栈
- **诊断日志** — 临时文件 `/tmp/hermes_reasoning_delta.log` 记录每次推理增量调用

### 中文思维支持

- **`prefill_chinese.json`** — 创建预填系统消息文件，要求模型在推理阶段使用中文
- **`prefill_messages_file` 配置** — `config.yaml` 指向预填文件，每次飞书对话自动注入

---

## [未发布] - 2026-04-29

### 思维面板实时流式输出

**问题**：思维面板内容一次性显示，无打字机效果。

**修复**：

- **`tool_panels.py`** — 思维面板内部 markdown 元素增加 `element_id='thinking_text'`，使 CardKit 可定位进行内容流式更新
- **`builder.py`** — `_build_reasoning_panel` 同样设置 `element_id='thinking_text'`
- **`streaming.py`** — 新增 `_stream_thinking_to_card()` 使用 `stream_card_content()` 进行实时流式渲染，0.3s 节流
- **`_handle_reasoning_delta`** — 优先走 CardKit 流式路径，回退到 `sync_thinking_card`（IM patch）

---

## [未发布] - 2026-04-29

### 推理链捕获修复

**问题**：DeepSeek V4 Pro 通过 `reasoning_content` 字段传输推理内容，但插件只从 `<think>` XML 标签提取，导致思维面板渲染但始终为空。

**修复**：

- 新增 `_handle_reasoning_delta()` 线程安全处理器，累积推理文本并调度异步 `sync_thinking_card()` 更新
- Monkey-patch `AIAgent._fire_reasoning_delta` 将推理增量路由到插件的思维管道（`remember_thinking_text` + CardKit）
- 在 `wrapped_send_or_edit` 中设置 `_current_feishu_consumer`，使处理器知道目标适配器和聊天

支持所有使用 `reasoning_content` / `thinking_delta` 的提供商（DeepSeek、MiniMax、Anthropic 等）。

---

## [未发布] - 2026-04-28

### 思维面板功能

- `sync_thinking_card` 发送完整卡片体 + 思维面板（非片段），修复 CardKit "body is nil" 错误
- `build_streaming_pre_answer_card` 新增 `thinking_panel` 参数
- 新增 `build_streaming_thinking_active_panel` / `build_streaming_thinking_pending_panel`
- `runtime_state` 新增 `remember_thinking_text` / `get_thinking_text` 用于思维文本累积
- `build_complete_card` 新增 `thinking_text` 参数，最终卡片中思维面板保持折叠
- `_finalize_card` 和 `abort_progress_card` 从 runtime_state 获取思维文本

---

## 2026-04-19

### 发布准备

- 完善安装说明
- CI：标签推送时发布
- 修复 npm 发布工作流守卫

---

## 2026-04-13

### 飞书卡片稳定性修复

- **修复**：卡片内嵌式 10 分钟心跳
- **修复**：审批卡恢复与流式正文保留
- **修复**：优化飞书工具面板折叠与进度刷新
- **修复**：修正飞书卡片更新与空工具区展示

---

## 2026-04-12

### 飞书流式卡片初始版本

- **修复**：修正飞书单卡流式与渠道切换展示
- **修复**：对齐飞书流式启动与本地化表现
