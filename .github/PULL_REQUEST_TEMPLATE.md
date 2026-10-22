<!--
中英双语：填中文或英文均可 / Bilingual: Chinese or English, either is fine.
提交前自检 / Before opening the PR:
- [ ] 目标分支是 develop（发版合并不走 PR，见 docs/RELEASE.md）/ Target branch is develop (release merges don't go through PRs — see docs/RELEASE.md)
- [ ] 纯逻辑测试全过（dev/ 下 6 个套件）/ All 6 pure-logic dev suites pass
- [ ] 改了 README 就中英两段同步更新 / README changes updated in both language sections
- [ ] 需要发版的改动已更新 CHANGELOG.md 的未发布段 / Releasable changes recorded under Unreleased in CHANGELOG.md
- [ ] 没带上 dev/cookie.txt、dev/ha_token.txt、.env / No dev/cookie.txt, dev/ha_token.txt or .env staged
-->

## 改动内容 / What changed

<!-- 一句话说明这个 PR 做什么 / One line on what this PR does -->

## 关联 issue / Related issues

<!-- Closes #123 -->

## 类型 / Type

- [ ] fix / 缺陷修复
- [ ] feat / 新功能
- [ ] docs / 文档
- [ ] test / 测试
- [ ] refactor / 重构
- [ ] release / 发布（仅维护者 / maintainer only）

## 测试与验证 / Testing & verification

<!-- 本地跑了哪些测试、HA 里验证了什么 / Which suites ran locally, what was verified in HA -->

## 风险与回滚 / Risks & rollback

<!-- 涉及实体 unique_id、配置项语义、接口调用形态等高敏感改动时必填 / Required for sensitive changes: entity unique_id, config semantics, API call shapes -->
