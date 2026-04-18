# 项目级约定 — 每个新 session 自动加载

## 环境
- 当前: Windows 11, PowerShell 5.1, Python 3.12, Git 2.42
- 链式命令用 `; if ($?) { }` 不用 `&&`
- 删目录用 `Remove-Item -Recurse -Force` 不用 `rm -rf`
- Python 命令用 `python` 不用 `python3`

## Skill 规则
- 所有 skill 存放在 `D:\code\game\skills\{name}/`
- 除非明确说"放全局"，否则项目级
- 必须包含 SKILL.md，可选 reference.md

## Memory 使用
- 用户偏好/环境信息 → scope: user（跨项目）
- 项目特定知识 → scope: project
- 每个 session 启动时 recall tags: ["session", "startup"] 获取检查清单

## Git 约定
- commit 格式: `feat(task/T001): 简述` / `fix(task/T002): ...` / `analysis(task/T003): ...`
- `*.db` 已 gitignore
- `hs_cards/images/` 和 `hs_cards/crops/` 已 gitignore
