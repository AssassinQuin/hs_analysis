# 项目级约定 — 每个新 session 自动加载

## 环境（跨平台）

本项目支持 **macOS + Windows** 双平台。每次 session 启动时自动检测：

- 运行 `uname -s 2>/dev/null || echo "Windows"` 判断平台
- 检测结果写入上下文，后续所有命令自动适配

| 平台 | Shell | 删目录 | 链式命令 | Python |
|------|-------|--------|----------|--------|
| macOS (Darwin) | zsh/bash | `rm -rf` | `&&` | `python3` |
| Windows | PowerShell | `Remove-Item -Recurse -Force` | `; if ($?) { }` | `python` |

## 工具优先级

```
MCP 工具 > OpenCode 内置 > 子代理
```

- 同一功能有 MCP 和 OpenCode 两种实现时，**选 MCP**
- 例：代码搜索用 `ast_grep_search` 而非 `grep`；文件读取用 `read` 而非手动 `cat`

## Skill 规则

- 项目级 skill 在 `.opencode/skills/{name}/`（OpenCode 自动加载）
- 全局 skill 在 `~/.config/opencode/skills/` 或 `~/.opencode/skills/`
- 必须包含 `SKILL.md`（含 YAML frontmatter: name + description）
- **研究/调研任务**必须加载对应 skill，遵循 skill 中的方法论
- 当前可用项目 skill：
  - `card-modeling` — 卡牌数学建模（5-phase 科学方法论）

## 大文件生成策略

- **>500 行的文件**必须分步生成：先骨架（imports + class 定义 + method 签名），再填充
- 每次写入不超过 200 行
- 未填充部分标记 `# TODO: implement`
- 写完一个模块后运行测试再继续

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
