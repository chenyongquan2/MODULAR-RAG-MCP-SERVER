# .specify/ —— 已冻结(2026-08-12)

**本目录只读。GitHub Spec-Kit 已从本项目退役,这里的模板与脚本不再被任何流程调用。**

现行 SDD 是 **OpenSpec**:流程见 [CLAUDE.md § Mandatory SDD Workflow](../CLAUDE.md),
项目底座见 [openspec/config.yaml](../openspec/config.yaml)。

## 里面是什么

| 路径 | 说明 |
|---|---|
| `memory/constitution.md` | **宪法 v1.0.0 原文**(2026-04-25 立宪)。作为 ADR 留档 —— 它的**效力已转移**到 `openspec/config.yaml` 的 `context:` 字段。七条核心原则原样保留,Rule VIII/IX/X(spec 先行 / plan 先于 tasks / commit 引用 task ID)中 Rule IX 随相位门一并取消,VIII 与 X 降级为约定 |
| `templates/` | Spec-Kit 的 spec / plan / tasks / checklist / constitution 模板,已失效 |
| `scripts/bash/` | `check-prerequisites.sh` 等前置校验脚本,已失效 |
| `extensions/git/` | Spec-Kit 的 git 扩展(auto-commit、create-new-feature 等),已失效 |
| `archived-skills/` | 8 个停用的 `speckit-*` Claude Code skill。**存在这里是因为 `.claude/` 被 gitignore** —— 直接删就不可恢复,移到跟踪目录以便回滚 |
| `workflows/`、`integrations/`、`feature.json` 等 | Spec-Kit 运行期配置,已失效 |

## 如果要回滚到 Spec-Kit

1. 把 `archived-skills/speckit-*` 移回 `.claude/skills/`
2. 恢复 `CLAUDE.md` 的 § Mandatory SDD Workflow 与 Active Feature 块(见该文件的 git 历史,迁移 commit 在 2026-08-12)
3. `docs/sdd-guide.md` 去掉顶部的废弃横幅

反过来,若确认不再回滚,整个目录可以删除 —— 但先把 `memory/constitution.md` 搬到
`docs/decisions/`,它是有历史价值的决策记录。
