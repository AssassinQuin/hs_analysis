# 项目级约定 — 每个新 session 自动加载

## 环境
- 当前: macOS (Darwin), Python 3.11, Git, zsh
- 标准 POSIX 命令（`rm -rf`, `&&`, `python3` 均可用）

## Skill 规则
- 项目级 skill 存放在 `.opencode/skills/{name}/`（OpenCode 自动加载）
- 全局 skill 在 `~/.config/opencode/skills/` 或 `~/.opencode/skills/`
- 必须包含 `SKILL.md`（含 YAML frontmatter: name + description）
- 可选 `reference.md` 或其他辅助文件

## Memory 使用
- 用户偏好/环境信息 → scope: user（跨项目）
- 项目特定知识 → scope: project
- 每个 session 启动时 recall tags: ["session", "startup"] 获取检查清单

## Git 约定
- commit 格式: `feat: / fix: / cleanup: 简述`
- `__pycache__/` 和 `.pytest_cache/` 已 gitignore
- `hs_cards/images/` 和 `hs_cards/crops/` 已 gitignore
- `*.db` 已 gitignore

## 代码约定
- 核心逻辑在 `hs_analysis/` 包内，`scripts/` 仅放运行入口
- import 用 `from hs_analysis.xxx import yyy`，不用 `sys.path` hack
- 测试放 `tests/` 或模块内 `test_*.py`
- dataclass 用于数据模型，类型注解全覆盖
