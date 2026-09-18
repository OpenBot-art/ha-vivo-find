# 贡献指南 / Contributing

[中文](#中文) · [English](#english)

---

## 中文

### 分支模型

本仓库采用「双分支」模型，`main` 只放可发布的稳定版：

| 分支 | 角色 | 规则 |
|---|---|---|
| `main` | **稳定发布分支** | 只接受来自 `develop` 的合并。任何提交到 `main` 的代码都必须是「用户装上就能用」的状态 |
| `develop` | **日常开发分支** | 所有功能、修复、重构都先提到这里。默认工作分支 |
| `feat/*`、`fix/*`、`docs/*` | 临时分支 | 从 `develop` 切出，完成后合并回 `develop`，然后删除 |

```
main      ──●────────────────●──────────●──▶  只合入验证过的版本
             ╲              ╱          ╱
develop      ●──●──●──●──●──●──●──●──●──▶  日常开发
                ╲   ╱    ╲  ╱
feat/xxx         ●─●      ●─●                临时分支，用完即删
```

### 日常工作流

```bash
# 1. 从 develop 切出临时分支
git checkout develop
git pull origin develop
git checkout -b fix/address-empty

# 2. 改代码，跑测试
python dev/test_parse.py
python dev/test_crs.py
python dev/test_address.py

# 3. 提交（遵循下面的提交信息规范）
git add -A
git commit -m "fix: 首轮跳过定位导致地址为空"

# 4. 推送并开 PR 到 develop
git push -u origin fix/address-empty
gh pr create --base develop --fill
```

### 发布流程

```bash
# 1. 确认 develop 上测试全绿
git checkout develop && git pull

# 2. 合并到 main（用 --no-ff 保留「这是一次发布」的记录）
git checkout main && git pull
git merge --no-ff develop -m "release: v1.4.0"
git push origin main

# 3. 打 tag（HACS 靠 tag 识别版本）
git tag -a v1.4.0 -m "v1.4.0"
git push origin v1.4.0

# 4. 同步回 develop，避免两边分叉
git checkout develop
git merge --ff-only main
git push origin develop
```

> ⚠️ **发版必做**：`custom_components/vivo_find/manifest.json` 里的 `version`
> 必须和 tag 一致。HACS 是按 tag 拉版本的，版本号对不上会出现「装上了但不是新版」。

### 提交信息规范

采用 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/)，
用中文写正文，动词开头：

| 前缀 | 用途 | 例子 |
|---|---|---|
| `feat:` | 新功能 | `feat: 支持多设备同时追踪` |
| `fix:` | 修 bug | `fix: 限流时误判为离线` |
| `docs:` | 文档 | `docs: 补充坐标系排查步骤` |
| `chore:` | 杂项（依赖、配置、脱敏） | `chore: 补 .gitattributes` |
| `refactor:` | 重构，不改行为 | `refactor: 抽出 crs.py` |
| `test:` | 测试 | `test: 补定位冷却的边界用例` |
| `release:` | 发布合并 | `release: v1.4.0` |

### 提交前自检清单

- [ ] 纯逻辑测试全过：`python dev/test_parse.py`、`dev/test_crs.py`、`dev/test_address.py`
- [ ] 没把 `dev/cookie.txt`、`dev/ha_token.txt` 提上来（`git status` 确认）
- [ ] 新增的实体属性有对应 README 说明
- [ ] 改了坐标系结论的话，同步更新 README 的坐标系一节
- [ ] 改了 `manifest.json` 的 `version` 时，记得它是跟 tag 走的

### 测试约定

- **`dev/test_api.py` 撞限流算 SKIP 不算 FAIL** —— vivo 的 `operate` 接口有限流，
  这不是代码问题
- **`dev/_loader.py` 的 `make_status(desc=None)` 默认不给地址是故意的** ——
  真实 `devicestatus` 就不给地址。别为了方便把它改回去，那会掩盖
  「首轮跳过定位 → 地址变空」这个 bug
- 纯逻辑测试用桩替换 HA 依赖，**不需要装 Home Assistant 也能跑**

---

## English

### Branch model

This repository uses a two-branch model. `main` holds only releasable, stable code:

| Branch | Role | Rules |
|---|---|---|
| `main` | **Stable release branch** | Only accepts merges from `develop`. Anything on `main` must be in a "users can install it and it works" state |
| `develop` | **Daily development branch** | All features, fixes and refactors land here first. This is the default working branch |
| `feat/*`, `fix/*`, `docs/*` | Topic branches | Cut from `develop`, merged back into `develop`, then deleted |

```
main      ──●────────────────●──────────●──▶  verified releases only
             ╲              ╱          ╱
develop      ●──●──●──●──●──●──●──●──●──▶  day-to-day work
                ╲   ╱    ╲  ╱
feat/xxx         ●─●      ●─●                short-lived topic branches
```

### Day-to-day workflow

```bash
# 1. Cut a topic branch from develop
git checkout develop
git pull origin develop
git checkout -b fix/address-empty

# 2. Make changes, run tests
python dev/test_parse.py
python dev/test_crs.py
python dev/test_address.py

# 3. Commit (see the commit message convention below)
git add -A
git commit -m "fix: empty address caused by first-poll locate skip"

# 4. Push and open a PR against develop
git push -u origin fix/address-empty
gh pr create --base develop --fill
```

### Release process

```bash
# 1. Make sure develop is green
git checkout develop && git pull

# 2. Merge into main (use --no-ff so the release stays visible in history)
git checkout main && git pull
git merge --no-ff develop -m "release: v1.4.0"
git push origin main

# 3. Tag (HACS resolves versions by tag)
git tag -a v1.4.0 -m "v1.4.0"
git push origin v1.4.0

# 4. Sync back into develop so the branches don't diverge
git checkout develop
git merge --ff-only main
git push origin develop
```

> ⚠️ **Release gotcha**: the `version` field in
> `custom_components/vivo_find/manifest.json` must match the tag. HACS pulls
> releases by tag; a mismatch shows up as "it installed, but it's not the new version".

### Commit message convention

We follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/).
Write the body in English or Chinese, start with a verb:

| Prefix | Purpose | Example |
|---|---|---|
| `feat:` | New feature | `feat: track multiple devices at once` |
| `fix:` | Bug fix | `fix: throttled responses reported as offline` |
| `docs:` | Documentation | `docs: add coordinate system troubleshooting steps` |
| `chore:` | Chores (deps, config, redaction) | `chore: add .gitattributes` |
| `refactor:` | Refactor, no behaviour change | `refactor: extract crs.py` |
| `test:` | Tests | `test: cover locate cooldown edge cases` |
| `release:` | Release merge | `release: v1.4.0` |

### Pre-commit checklist

- [ ] Pure-logic tests pass: `python dev/test_parse.py`, `dev/test_crs.py`, `dev/test_address.py`
- [ ] `dev/cookie.txt` and `dev/ha_token.txt` are not staged (check `git status`)
- [ ] New entity attributes are documented in the README
- [ ] If you changed the coordinate-system conclusion, update the README section too
- [ ] If you bumped `manifest.json`'s `version`, remember it must track the tag

### Testing conventions

- **A rate-limit hit in `dev/test_api.py` is a SKIP, not a FAIL** — vivo's
  `operate` endpoint is rate limited; that is not a code problem
- **`make_status(desc=None)` in `dev/_loader.py` deliberately provides no address** —
  the real `devicestatus` response doesn't either. Don't "fix" this for convenience:
  it would mask the "first poll skips locate → address goes empty" bug
- Pure-logic tests stub out the HA dependency, so **you can run them without
  installing Home Assistant**
