# 更新日志 / Changelog

本文件遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，
版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)。每个版本同时提供
中文与英文说明，**两边都要更新**。

---

## [1.4.0] - 2026-10-23

### 中文

**新增**

- **零限流推荐配置文档**：README 增补「零限流模式」章节 —— 轮询间隔 600 秒 +
  关闭「每次刷新下发定位指令」，全程只读 `devices` + `devicestatus`，
  永不下发定位指令
- **CI 新增两项检查**（`validate-repo.yml`）：`manifest.json` 版本与 git tag
  一致性、README 中英双语段落同步
- 新增 `CONTRIBUTING.md`（分支模型 / 提交规范 / 测试约定）与
  `docs/RELEASE.md`（发布 SOP 与回滚预案）

**修复**

- **设备命名统一**：新增 `const.resolve_device_name()` 作为设备名的唯一来源
  （别名 > entry.title > 兜底），`device_tracker` 与 `sensor` 不再各取各的，
  避免同名设备被 HA 归到两张卡片下
- **传感器可用性**：单轮刷新失败（限流 / 网络抖动）时，有任一有效数据的传感器
  不再集体变「不可用」——与 `device_tracker` 的可用性语义对齐
- `config_flow` 在别名为空时明确退到机型名并打日志，说清实体 ID 的成因

**测试**

- 新增 `dev/test_naming.py`（19 项）与 `dev/test_availability.py`（12 项），
  并纳入 CI

### English

**Added**

- **Zero-rate-limit recommended configuration** documented in the README:
  600 s polling + "locate on every refresh" off — only `devices` and
  `devicestatus` are read, no locate command is ever issued
- **Two new CI checks** (`validate-repo.yml`): `manifest.json` version vs git
  tag consistency, and README bilingual section sync
- New `CONTRIBUTING.md` (branch model / commit convention / testing rules) and
  `docs/RELEASE.md` (release SOP + rollback plan)

**Fixed**

- **Unified device naming**: new `const.resolve_device_name()` as the single
  source of the device name (alias > entry.title > fallback); `device_tracker`
  and `sensor` no longer derive names independently
- **Sensor availability**: sensors with any valid data no longer all go
  "unavailable" on a single failed refresh (rate limit / network blip) —
  aligned with `device_tracker`'s availability semantics
- `config_flow` now falls back to the model name with an explicit log line when
  the alias is empty, explaining the resulting entity ID

**Tests**

- New `dev/test_naming.py` (19 cases) and `dev/test_availability.py` (12 cases),
  both wired into CI

---

## [1.3.0] - 2026-09-19

首个公开发布版本 / First public release.

### 中文

**新增**

- `device_tracker` GPS 实体 + 6 个传感器（电量 / 充电 / 在线 / 地址 / 网络 /
  定位时间），可直接放进 HA 地图卡片
- 配置流程（UI 添加集成）：cookie 校验、设备单选、轮询间隔、定位开关、
  坐标系选择；cookie 过期自动弹出重新认证
- `vivo_find.locate_now` 服务：手动立刻定位，走独立冷却通道
- 限流三层防护：定位指令 300 秒冷却、撞限流可恢复不清数据、
  `locate_throttled` 状态透出
- BD-09 → WGS84 坐标转换（实测 vivo 接口返回百度坐标，不转地图偏约 1.2 公里）
- 上次成功数据持久化 + 首轮避让 + 快速重试，重启后不白等一个周期
- CI：hassfest、HACS action、纯逻辑测试流水线

### English

**Added**

- A GPS `device_tracker` entity plus 6 sensors (battery / charging / online /
  address / network / fix time), ready for the HA map card
- Config flow: cookie validation, single-device selection, polling interval,
  locate toggle, coordinate-system choice; automatic re-authentication when the
  cookie expires
- `vivo_find.locate_now` service: locate immediately through a separate
  cooldown channel
- Three-layer rate-limit protection: 300 s cooldown between locate commands,
  recoverable throttling that never blanks data, and a visible
  `locate_throttled` attribute
- BD-09 → WGS84 coordinate conversion (the vivo API returns Baidu coordinates;
  skipping this shifts the map pin by ~1.2 km)
- Persistence of the last successful snapshot + first-refresh avoidance + fast
  retries, so a restart does not waste a polling cycle
- CI: hassfest, HACS action, and pure-logic test pipelines
