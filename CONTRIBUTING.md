# Contributing to hermes-feishu-plugin-1

🎉 感谢你关注 hermes-feishu-plugin-1！以下是参与贡献的方式。

---

## 开发环境

```bash
# 克隆
git clone https://github.com/zirflow/hermes-feishu-plugin-1.git
cd hermes-feishu-plugin-1

# 安装依赖
pip install -e .

# 运行测试
pytest tests/ -v
```

---

## 分支规范

- `main` — 稳定版本，只接受 PR 合并
- `feat/*` — 新功能开发分支
- `fix/*` — Bug 修复分支
- `refactor/*` — 重构分支

命名格式：`feat/your-feature-name`

---

## 开发流程

1. Fork 本仓库，创建分支：`git checkout -b feat/your-feature`
2. 开发 + 写测试
3. 确保所有测试通过：`pytest tests/ -v`
4. 提交，push 到你的 Fork
5. 提 Pull Request，描述改动内容和动机

---

## 代码规范

- Python ≥ 3.11
- 使用 `ruff` 做 lint：`ruff check src/ tests/`
- 使用 `ruff format` 格式化：`ruff format src/ tests/`
- 提交信息格式：`type(scope): description`
  - `feat`: 新功能
  - `fix`: Bug 修复
  - `docs`: 文档
  - `refactor`: 重构
  - `test`: 测试
  - `chore`: 维护

---

## 测试规范

所有新功能必须包含测试。测试文件放在 `tests/`，与 `src/` 目录结构对应。

```bash
# 运行单个测试文件
pytest tests/test_streaming.py -v

# 带覆盖率
pytest tests/ --cov=src --cov-report=term-missing
```

---

## 发布流程

版本号遵循 [Semantic Versioning](https://semver.org/)：
- `MAJOR.MINOR.PATCH`
- `1.0.0` → `1.1.0`（新功能，向后兼容）
- `1.0.0` → `2.0.0`（破坏性变更）

---

## 许可证

贡献即表示你同意你的代码以 [Apache-2.0](LICENSE) 许可证发布。
