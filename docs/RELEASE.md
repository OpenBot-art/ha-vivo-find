# 发布流程（HACS）/ Release Process

[English](#english) | **简体中文**

---

## 中文

本文是 ha-vivo-find 的**发布 SOP**。分支模型与日常工作流见
[CONTRIBUTING.md](../CONTRIBUTING.md)；本文只讲「怎么发版、怎么验证、怎么回滚」。

### 0. 发版前置检查（缺一不可）

| # | 检查项 | 怎么确认 |
|---|---|---|
| 1 | develop 上测试全绿 | `python dev/test_parse.py` 等 6 个套件 + CI 全绿 |
| 2 | `CHANGELOG.md` 已写好该版本条目 | 中英文两段都有 |
| 3 | `manifest.json` 的 `version` 已改成待发布版本号 | 与即将打的 tag 一致（CI 会查） |
| 4 | `README.md` 中英双语同步更新 | CI 的 `validate-repo` 会查比例 |
| 5 | 工作区干净，无本地调试残留 | `git status` |

### 1. 标准发布流程

```bash
# 1) 确认 develop 全绿后，合并到 main（--no-ff 保留「这是一次发布」的记录）
git checkout main && git pull
git merge --no-ff develop -m "release: v1.4.0"

# 2) 打 annotated tag —— HACS 靠 tag 识别版本，号必须与 manifest 一致
git tag -a v1.4.0 -m "v1.4.0"
git push origin main
git push origin v1.4.0

# 3) 同步回 develop，避免两边分叉
git checkout develop
git merge --ff-only main
git push origin develop
```

推送后 CI 会自动跑四道校验：hassfest、HACS action、纯逻辑测试、
`validate-repo`（版本一致性 + README 双语）。**全绿才算发布成功**，
红了先修再说话。

### 2. 测试版本流程（可选，用于先验证 HACS 更新体验）

重大改动建议先发一个测试 tag，在真实 HA 里走过一遍 HACS 更新，
确认无误再发正式版：

```bash
# 在 main 上（或包含发布提交的 ref 上）打测试 tag
git tag -a v1.4.0-test.1 -m "v1.4.0 测试版"
git push origin v1.4.0-test.1
```

在 HA → HACS → 本集成里触发更新，验证：

- 能检测到新版本并正常下载
- 重载后实体不丢、不出「未知」
- 地图上的点、地址、电量符合预期

确认无误后**删除测试 tag**，再走上面的标准流程打正式 tag：

```bash
git tag -d v1.4.0-test.1
git push origin :refs/tags/v1.4.0-test.1
```

> ⚠️ **删 tag 是不可逆的对外动作**：已经有人按这个 tag 装过，删了之后
> HACS 列表里会显示「版本不存在」。测试 tag 只在自己验证阶段用，
> 别让用户有窗口期装到它。验证完立刻删。

### 3. 回滚预案

| 情况 | 处理 |
|---|---|
| CI 在 main 上挂了 | 先修 develop，**另发一个修复版**（如 v1.4.1），不要删已推送的 tag 重打同号 |
| 用户报「装上不是新版」 | 99% 是 manifest.version 与 tag 不一致，对照 CI 的版本检查修 |
| 发布后发现问题、但 tag 已推送 | 走热修复流程：develop 修 → 合 main → 发修复版本号，**绝不删 tag/改已发布历史** |
| HACS 侧缓存不刷新 | 让用户在 HACS 集成页右上角「⋯ → 重新下载」；仍不行删掉重装 |

**核心原则：版本只前进，不回头。** 删 tag、`push --force` 改 main
这类操作会直接伤害已经装上的用户，任何情况下都不要做。

### 4. 版本号规则

遵循语义化版本 `MAJOR.MINOR.PATCH`：

- `PATCH`：缺陷修复、文案修正（如 1.3.0 → 1.3.1）
- `MINOR`：向后兼容的新功能（如 1.3.0 → 1.4.0）
- `MAJOR`：破坏性变更（配置项语义变化、实体 unique_id 规则变化等）

`manifest.json` 的 `version` 与 tag **必须逐字一致**，这是 CI 硬性检查。

---

## English

This is the **release SOP** for ha-vivo-find. For the branch model and
day-to-day workflow see [CONTRIBUTING.md](../CONTRIBUTING.md); this document
covers only how to release, how to verify, and how to roll back.

### 0. Pre-release checklist (all required)

| # | Item | How to verify |
|---|---|---|
| 1 | All tests green on `develop` | 6 dev suites + all CI checks |
| 2 | `CHANGELOG.md` has the entry | Both language sections |
| 3 | `manifest.json` `version` bumped | Must match the tag you are about to push (CI enforces) |
| 4 | `README.md` bilingual sync | Enforced by the `validate-repo` CI check |
| 5 | Clean working tree | `git status` |

### 1. Standard release

```bash
git checkout main && git pull
git merge --no-ff develop -m "release: v1.4.0"

git tag -a v1.4.0 -m "v1.4.0"
git push origin main
git push origin v1.4.0

git checkout develop
git merge --ff-only main
git push origin develop
```

After pushing, CI runs four checks: hassfest, HACS action, pure-logic tests,
and `validate-repo` (version consistency + README bilingual sync).
**The release only counts when everything is green.**

### 2. Test-release flow (optional, verifies the HACS update experience)

For significant changes, push a test tag first and walk through the HACS
update in a real HA instance:

```bash
git tag -a v1.4.0-test.1 -m "v1.4.0 test release"
git push origin v1.4.0-test.1
```

In HA → HACS → this integration, trigger the update and verify:

- The new version is detected and downloads correctly
- After reload, no entities are lost or show as "unknown"
- Map pin, address, and battery all behave as expected

Once verified, **delete the test tag**, then follow the standard flow above
for the real tag:

```bash
git tag -d v1.4.0-test.1
git push origin :refs/tags/v1.4.0-test.1
```

> ⚠️ **Deleting a tag is an irreversible external action.** Anyone who
> installed from it will see "version not found" in HACS. Test tags are for
> your own verification only — delete them immediately so users never have a
> window to install one.

### 3. Rollback plan

| Situation | Action |
|---|---|
| CI fails on `main` | Fix on `develop` and ship a **fix release** (e.g. v1.4.1); never delete and re-push the same tag |
| Users report "installed but not the new version" | Almost always a manifest/tag mismatch — fix per the CI version check |
| Problem found after the tag is pushed | Hot-fix flow: fix `develop` → merge to `main` → ship a new patch version. **Never delete tags or rewrite published history** |
| HACS cache is stale | Have the user use "⋯ → Reload" on the integration page; if that fails, remove and re-add |

**Core principle: versions only move forward.** Deleting tags or
force-pushing `main` directly harms users who already installed — never do it.

### 4. Versioning

Semantic versioning `MAJOR.MINOR.PATCH`:

- `PATCH`: bug fixes, copy edits (1.3.0 → 1.3.1)
- `MINOR`: backward-compatible features (1.3.0 → 1.4.0)
- `MAJOR`: breaking changes (config semantics, entity unique_id rules, etc.)

`manifest.json`'s `version` and the tag must match **exactly** — this is a
hard CI check.
