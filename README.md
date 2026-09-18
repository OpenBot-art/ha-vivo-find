# VIVO 查找设备 · Home Assistant 集成

把 vivo 云服务（find.vivo.com.cn）里手机的**实时位置**接进 Home Assistant，
生成一个标准的 GPS `device_tracker` 实体，可以直接在 HA 地图卡片上看到你的设备。

> 这是纯本地集成：所有请求从你的 HA 直接发往 vivo 云服务，
> **不经任何第三方服务器**，cookie 只存在你自己的 HA 配置里。

---

## 它给你什么

| 实体 | 类型 | 说明 |
|---|---|---|
| `device_tracker.iqooo` | **GPS 追踪器** | 地图上的那个点。带 `latitude` / `longitude` / `location_accuracy` / `battery_level` |
| `sensor.iqooo_battery` | 传感器 | 电量 % |
| `sensor.iqooo_charging` | 传感器 | 充电中 / 未充电 |
| `sensor.iqooo_online` | 传感器 | 在线 / 离线 |
| `sensor.iqooo_address` | 传感器 | 文字地址，例如「黄鹤楼公园，湖北省武汉市武昌区…」。属性里带 `locate_status` / `address_age_s`，为空时会给出原因 |
| `sensor.iqooo_network` | 传感器 | 5G / WiFi 名 |
| `sensor.iqooo_fix_time` | 传感器 | 这次定位的时间戳（判断位置有多"新"） |

`device_tracker` 的附加属性里还有：

- **地址相关**：`address`、`address_time`（这个地址哪一刻拿到的）、
  `address_age_s`（距今多少秒 —— 判断地址新旧**看它，不是看 `fix_time`**）
- **定位诊断**：`locate_status`（本轮定位的结果，状态码见下面「地址」一节）、
  `located_live`（坐标是新定位的还是缓存）、`locate_throttled`、
  `position_age_s`（坐标距今多少秒）、`last_update_success`
  （本轮拉取是否成功；`false` 表示当前值来自缓存）
- **设备状态**：`online`、`online_raw`、`accuracy`、`network`、`signal_strength`、
  `operator`、`charging`、`device_model`、`imei`
- **坐标系排查**：`raw_coordinates` / `coordinates` / `source_crs` / `target_crs`
  （见下面「坐标系」一节）

> 实体 ID 按设备别名生成，例如设备别名是 `iQOOO` 时实体就是
> `device_tracker.iqooo`。在「开发者工具 → 状态」里搜 `vivo_find` 或你的设备名可确认。

---

## 安装

### 方式一：HACS 自定义仓库

1. HACS → 集成 → 右上角三点 → **自定义存储库**
2. 填入本仓库地址，类别选 **集成(Integration)**
3. 搜索「VIVO 查找设备」→ 下载 → **重启 Home Assistant**

### 方式二：手动拷贝

把 `custom_components/vivo_find` 整个文件夹复制到 HA 配置目录下：

```
<你的HA配置目录>/
└── custom_components/
    └── vivo_find/
        ├── __init__.py
        ├── api.py
        ├── config_flow.py
        ├── const.py
        ├── coordinator.py
        ├── crs.py
        ├── device_tracker.py
        ├── sensor.py
        ├── manifest.json
        ├── strings.json
        └── translations/
```

然后**重启 Home Assistant**。

---

## 配置

1. 浏览器打开 <https://find.vivo.com.cn/> 并登录（**勾选「14 天内免登录」**，
   之后保持访问可以让 cookie 长期有效）
2. 按 `F12` → **网络(Network)** → 刷新页面 → 点任意一个请求
3. 在请求头里找到 `Cookie`，**整段复制**。必须包含 `vivo_yun_csrftoken=` 这一段，
   少了它集成会直接告诉你缺字段（这是刻意做的检查，不然只会报一个看不懂的错）
4. HA → 设置 → 设备与服务 → **添加集成** → 搜「VIVO 查找设备」
5. 粘贴 cookie，填设备名称（**只有一台设备时可以留空**），设轮询间隔

| 配置项 | 默认 | 说明 |
|---|---|---|
| Cookie | 必填 | 上面那段 |
| 设备名称 | 空 | 单设备留空；多设备填**完整别名**（大小写敏感，例如 `iQOOO`） |
| 轮询间隔 | 600 秒 | 建议 ≥300 秒，太频繁会撞限流 |
| 每次刷新下发定位指令 | 开 | 见下面「关于限流」 |
| 坐标系（接口返回） | `BD-09 百度坐标` | 实测确认，**不要改**，理由见下节 |
| 坐标系（输出给 HA） | `WGS84` | HA 标准。只有用高德底图卡片时才改 |

Cookie 过期后 HA 会**自动弹出「重新认证」**让你贴新 cookie，不用删掉重加。

---

## ⚠️ 坐标系 —— 地图位置偏了 1.2 公里的根因

**如果你发现地图上的点跟实际位置差了一大截（不是几十米，是上千米），就是这里。**

国内有三套坐标系，互相不通用：

| 坐标系 | 谁在用 |
|---|---|
| **WGS84** | GPS 原始输出、OpenStreetMap、**Home Assistant 内部标准** |
| **GCJ-02**（火星） | 高德、腾讯、国内合规地图 |
| **BD-09**（百度） | 百度地图 |

**实测结论：vivo 接口返回的是 BD-09。** 而 HA 的 `device_tracker`、`zone`、
`person` 判定和默认地图底图全部基于 WGS84。所以**不转换的话，地图上的点会偏约 1200 米**
（实测：lng +0.012017 / lat +0.003223）。

本集成默认已按 `BD-09 → WGS84` 转换，装在 HA 上就是对的。

### 这个结论是怎么来的

> 下面演示用的坐标取武汉黄鹤楼一带的**公开地标**，实测原始点位已作脱敏；
> 参照点全部来自高德真实 POI，换任意坐标复算都能得到同样结论。

设接口返回 `114.309931, 30.550455`，自报地址「黄鹤楼公园，…武昌区蛇山西山坡特1号」。
把原值按三种假设分别换算成「高德应该显示的点」，再跟高德的门牌级数据比：

| 参照点（高德 GCJ-02） | 按 BD-09 解释 | 按 GCJ-02 解释 | 按 WGS84 解释 |
|---|---|---|---|
| 蛇山西山坡特1号 **门址** | **86 m** ✅ | 961 m | 1293 m |
| 黄鹤楼红墙 POI（横街69号） | **310 m** ✅ | 765 m | 1218 m |
| 胜像宝塔 POI（民主路56号） | **233 m** ✅ | 1049 m | 1423 m |
| 黄鹤楼公园西门售票处 | **248 m** ✅ | 1053 m | 1434 m |
| 黄鹤楼文创中心 | **221 m** ✅ | 940 m | 1147 m |

补充两条硬证据：

1. **门牌归属**：vivo 报的是「蛇山西山坡特1号」。高德数据显示「黄鹤楼红墙」的门牌是
   **横街69号**、「胜像宝塔」是**民主路56号**、「黄鹤楼公园西门售票处」是**西山坡特1号** ——
   都落在黄鹤楼景区内，距 BD-09 候选点 221~310 米。而按 GCJ-02 解释得到的候选点
   落在景区外的武昌老城区，对不上自报的地址。
2. **官方接口交叉**：高德官方坐标转换（`coordsys=baidu`）把原值转成
   `114.303346, 30.544794`，与本集成本地实现只差 **0.06 米**。

> 排查踩坑记录：最初只用单个 POI 做锚点，它距原值仅 121 米，差点误判成 GCJ-02。
> 后来发现那是巧合 —— BD-09 的偏移量恰好把 A 点搬到了 B 点附近，而这两个 POI
> 本来相距就有约 1 公里。
> **判坐标系必须用门牌级证据 + 多个独立锚点，单个 POI 会骗人。**

### 如果地图还是偏

先确认你用的是哪种地图，然后改「输出坐标系」：

| 你的地图卡片 | 「输出给 HA 的坐标系」应设为 |
|---|---|
| HA 自带 `type: map`（OpenStreetMap 底图） | `WGS84`（默认） |
| 高德底图的自定义卡片 | `GCJ-02` |

改法：设置 → 设备与服务 → VIVO 查找设备 → **配置** → 改「输出给 HA 的坐标系」。

`device_tracker` 的 `raw_coordinates`（接口原值）和 `coordinates`（转换后）
两个属性都暴露出来了，可以直接对照排查：

```
开发者工具 → 状态 → device_tracker.iqooo → 属性
  raw_coordinates: 114.309931,30.550455   ← vivo 给的 BD-09
  coordinates:     114.297915,30.547232   ← 实际画在 HA 地图上的 WGS84
  source_crs:      bd09
  target_crs:      wgs84
```

换城市、换设备后想重新验证，跑 `python dev/check_crs.py`，它会自动拉当前坐标、
用高德 POI 交叉比对，并告诉你 `source_crs` 该填什么。

---

## 在 HA 地图里显示

HA 的地图卡片只渲染 `device_tracker`（`source_type: gps`）和 `person` 实体。

**最简地图卡片：**

```yaml
type: map
default_zoom: 15
entities:
  - entity: device_tracker.iqooo
```

**想在某个 zone 里自动判断到家/离家，把它加进 person：**

设置 → 人员 → 编辑 person → 把 `device_tracker.iqooo` 加到「设备追踪器」里。
之后地图和自动化都能用 `person.xxx` 的状态（`home` / `not_home`）。

**自动化示例 —— 到家自动开灯，并且只在设备确实在线时触发：**

```yaml
alias: 到家开灯
trigger:
  - platform: state
    entity_id: person.long_ge
    to: home
condition:
  - condition: state
    entity_id: sensor.iqooo_online
    state: 在线
action:
  - service: light.turn_on
    target:
      entity_id: light.keting
```

**自动化示例 —— 电量低于 20% 提醒：**

```yaml
alias: 手机该充电了
trigger:
  - platform: numeric_state
    entity_id: sensor.iqooo_battery
    below: 20
action:
  - service: notify.mobile_app_xxx
    data:
      message: "手机电量 {{ states('sensor.iqooo_battery') }}%，地址：{{ state_attr('device_tracker.iqooo','address') }}"
```

---

## ⚠️ 关于限流（重要，务必看）

vivo 的「下发定位指令」（`operate`）接口**有限流**，实测连发几次就会返回
**「操作过于频繁」**，且**几分钟后才恢复**。集成对此做了三层处理：

1. **冷却**：两次定位指令之间强制间隔 300 秒，不会连续下发
2. **可恢复**：撞上限流**不算失败**，只记一条 WARNING，本次沿用最近一次位置，
   600 秒后再试。HA 里实体不会变不可用，地图上的点不会消失
3. **透出状态**：`device_tracker` 的 `locate_throttled` 属性会告诉你本次是否被限流

所以：

- 如果你在地图上发现坐标**不更新**，先看 `locate_throttled` 和 `fix_time`
- 想稳定拿到实时位置，**把轮询间隔拉到 600 秒以上**，而不是缩短
- 嫌麻烦可以把「每次刷新下发定位指令」关掉，只读上一次定位的缓存坐标 ——
  这样几乎不会撞限流，但位置可能滞后

> 还有一个实测发现：**限流期间 `devicestatus` 会返回空的电量/网络字段，
> 但不报错**。集成里做了「空值回退」——新数据为空时保留上一次的读数，
> 不会把你的电量传感器清成未知。

### 为什么重启 / 重载后第一轮常常取不到数据？

实测现象：HA 重启或集成重载后，第一轮刷新的电量、网络是空的，要再重载
一次才齐。两个原因叠在一起：

1. **首轮没有回退源。** 全新构造的协调器里没有任何历史值可参照，如果这一
   轮 `devicestatus` 恰好被限流（返回空的 `batteryInfo` / `signalInfo`，
   **且 `code` 正常、不报错**），就没东西能补上。
2. **首轮最容易撞限流。** HA 重启/重载通常紧跟上一轮定位之后（改配置、
   重启服务），vivo 端的限流窗口还没过，此时立刻发 `operate` 大概率被拒，
   还会把接下来几分钟的定位一起锁死。

v1.2.0 起做了三件事：

| 措施 | 作用 |
|---|---|
| 上次成功的数据落盘（`Store`） | 重启后先恢复，首轮就有电量 / 位置可显示 |
| 首轮若已从 `devicestatus` 拿到坐标，就不下发定位指令 | 不去撞限流窗口，第二轮起恢复正常定位 |
| 首轮数据不全时快速重试（2 次 × 5 秒） | 兜住「设备刚联网」这类秒级抖动（限流是分钟级，重试救不了） |

**副作用要知道**：重启后地图上的点可能是上一次定位时的位置，不是刚定的。
判断新鲜度看 `fix_time` 或 `position_age_s` 属性。

> 另外，实体的 `unique_id` 和名称已改为从**配置项里的静态值**生成，
> 不再依赖运行期数据。以前若首次刷新拿不到 imei，`unique_id` 会退化成兜底
> 值、下一次又变回真值，HA 会当成两个不同实体 —— 这也是「要重载一次才正常」
> 的来源之一。

### 地址（位置地址）为什么会变成「未知」

这是本集成最容易误解的一处，先说结论：

> **地址（`locationDesc`）只随「下发定位指令并成功」返回。**
> `devicestatus` 给的缓存位置**通常只有经纬度、没有门牌地址**。

实测对照（2026-09-18，同一台设备相隔一分钟）：

| 数据来源 | `locationDesc` | radius | `execMsg` |
|---|---|---|---|
| `devicestatus`（设备自己上报的位置） | **没有** ❌ | 6.0 | `10101__loctype-61` |
| `operate` + `polling`（我们下发定位后） | **有** ✅ | 40.0 | `10101__loctype-161` |

所以「地址为空」= 「这一轮没有成功下发定位指令」。具体是哪一种，看
`sensor.iqooo_address` 的 `locate_status` 属性（`device_tracker` 上也有）：

| `locate_status` | 含义 | 怎么办 |
|---|---|---|
| `ok` | 本轮定位成功，地址是新的 | 正常 |
| `throttled` | 被 vivo 限流（可恢复） | 等冷却结束，或手动补一次 |
| `timeout` | 定位指令超时（设备没联网/关机） | 会自动重试 |
| `failed` | 其他定位失败 | 会自动重试 |
| `skipped_cooldown` | 处于定位冷却窗口内，本轮没发指令 | 等下一轮 |
| `skipped_first_refresh` | 首轮避让（已有地址，主动跳过以避开限流窗口） | 正常 |
| `skipped_offline` | 设备离线 | 等设备联网 |
| `skipped_disabled` | 「每次刷新下发定位指令」被关掉了 | **地址不会更新，要么打开它，要么手动定位** |

几个要点：

- **关掉「每次刷新下发定位指令」= 地址永久不更新**。省配额可以理解，但代价是
  地址停在最后一次成功定位那一刻。想偶尔更新就用手动定位服务（见下一节）。
- 集成**不会**因为新数据没地址就把已有地址清空 —— 地址与它的时间戳（`address_time`）
  会一起保留下来。
- **`fix_time` 和 `address_time` 是两回事**：坐标可能刚更新，地址却还是几小时前的。
  想知道手里这个地址有多旧，看 `address_age_s`，别看 `fix_time`。
- v1.3.0 起，首轮避让只在「**已有坐标且已有地址**」时才生效。以前只看坐标，
  导致重启后首轮必然不发定位 —— 缓存里恰好没地址时，地址就永远补不回来。

---

### 想立刻刷新，不等下一个周期？

推荐用集成自带的 **`vivo_find.locate_now`**：它只做「下发定位并轮询」这一件事，
拿到结果后**直接推给实体**，不用等下一轮刷新，也不会因为冷却而空跑。

```yaml
service: vivo_find.locate_now
```

在「开发者工具 → 服务」里选 `VIVO 查找设备: 立刻定位` 即可，支持返回结果，
自动化里可以直接读到：

```yaml
# 示例：按一下无线开关就立刻定位一次
automation:
  - alias: 手动定位我的手机
    triggers:
      - trigger: state
        entity_id: sensor.wo_de_wu_xian_kai_guan_action
    actions:
      - action: vivo_find.locate_now
        response_variable: vivo_result
      - action: persistent_notification.create
        data:
          title: 手机定位
          message: "{{ vivo_result.results[0].result }}"
```

`force: true` 可以无视冷却强行下发（仅在确认限流已解除时用）。

也可以继续用 HA 的通用刷新服务，会触发一次完整刷新：

```yaml
service: homeassistant.update_entity
target:
  entity_id: device_tracker.iqooo
```

> 两者都不会绕过限流冷却 —— 连点不会把接口打爆，这是刻意的。
> `update_entity` 走常规刷新，冷却期内只会用缓存坐标；
> `locate_now` 则会明确告诉你「冷却中，还需 N 秒」。

---

## 排错

| 现象 | 原因 / 处理 |
|---|---|
| 添加时提示「Cookie 无效或已过期」 | cookie 过期，重新登录复制；确认含 `vivo_yun_csrftoken` |
| 提示「未找到匹配的设备」 | 多设备时名称必须和别名的**大小写完全一致** |
| 实体不可用、日志有 `读取状态被限流` | 等几分钟，或把轮询间隔调大 |
| 坐标不更新但实体正常 | 看 `locate_status`；或关闭定位指令开关 |
| **重启 / 重载后第一轮电量、位置为空** | v1.2.0 已修（落盘恢复 + 首轮避让限流）。若仍出现，看 `last_update_success` 与 `position_age_s` |
| 实体莫名多出一个、旧的变不可用 | v1.2.0 已修（unique_id 不再依赖运行期数据）。把多余的实体删掉即可 |
| **地图上的点偏了上千米** | 坐标系问题，见上面「坐标系」一节；对比 `raw_coordinates` 与 `coordinates` |
| **地址变成「未知」** | v1.3.0 已修（地址只随定位成功返回；以前首轮盲目避让会让它变空）。看 `locate_status` 定位原因，或调 `vivo_find.locate_now` 手动补一次 |
| **地址停在几小时前不动** | 正常现象 —— 地址只在定位成功时更新。看 `address_age_s`；想更新就打开定位开关或手动定位 |
| 电源/网络/地址字段一阵有一阵无 | vivo 限流期间会返回空字段但 `code` 正常，集成已做「空值回退」保留上次读数；配合 `locate_status` 判断 |

自检脚本（在能连到 HA 的机器上跑，会直接读出实体属性并给结论）：

```bash
# 把 HA 地址与长期令牌写进 dev/ha_token.txt（两行），或设 HA_URL / HA_TOKEN 环境变量
python dev/ha_probe.py
```

它还会顺手判断「你装的到底是不是新版代码」—— 属性里没有 `locate_status`
就说明还是旧版。

调试时把 `configuration.yaml` 的日志级别打开：

```yaml
logger:
  logs:
    custom_components.vivo_find: debug
```

vivo 是**私有接口**，字段结构随时可能变。哪天某个属性突然变未知，
先用 `dev/dump_status.py` 打印真实响应，再改 `coordinator.py` 的解析。

---

## 隐私与安全

- cookie 等价于你 vivo 账号的登录凭据，**能定位你的手机**。
  请确认你接受把凭据存在自己的 HA 配置里（`.storage/core.config_entries`）。
- 不要把这个集成连 cookie 一起发到公开仓库或群里。
  仓库里的 `dev/cookie.txt` 已在 `.gitignore` 中。
- 本集成只读：只调用「查设备 / 查状态 / 查找设备」，不发送任何修改类指令。

---

## 开发 / 测试

```bash
# 准备（仅开发需要）
python -m venv .venv && .venv/bin/pip install aiohttp
echo '<你的cookie>' > dev/cookie.txt      # 或 export VIVO_COOKIE='...'

# 纯逻辑单元测试（不需要网络、不需要 HA）
python dev/test_parse.py

# 坐标系转换测试（含高德官方接口交叉验证）
python dev/test_crs.py

# 地址 / 定位状态逻辑测试
python dev/test_address.py

# 端到端测试（真实调用 vivo 接口）
python dev/test_api.py

# 诊断：判定接口返回的坐标系（换城市 / 换设备后重新验一遍）
python dev/check_crs.py

# 诊断：地址为什么是空的 / 有多旧
python dev/check_address.py

# 诊断：直接读线上 HA 的实体状态与日志（需 dev/ha_token.txt）
python dev/ha_probe.py
```

- `dev/test_parse.py` —— 用桩替换 HA 依赖，测 `_pick` / `_parse_network` /
  `_parse_fix_time` / `merge_with_previous` 这些纯函数
- `dev/test_restore.py` —— 测「重启后首轮数据不全」的修复：序列化往返与容错、
  缓存兜底、首轮避让定位指令、首轮失败时有缓存不抛异常
- `dev/test_address.py` —— 测「地址只随定位成功返回」这层等价关系：
  首轮该不该下发定位、限流/超时/冷却/离线/开关关闭各自的状态码、
  `address_time` 与 `fix_time` 分离、`locate_now` 的冷却拦截与 force 放行
- `dev/test_crs.py` —— 测 `crs.py` 的三种坐标系互转：本地往返一致性、
  境外不偏移、实测 BD-09 锚点反推，并与**高德官方转换接口**逐点对照（误差 <5m）
- `dev/test_api.py` —— 真实打通 vivo 四个接口，并校验经纬度没写反
  （武汉是 lat 30.x / lon 114.x，写反了会立刻被抓出来）
- `dev/check_crs.py` —— 拉当前坐标 + 高德 POI 交叉比对，输出 `source_crs` 建议值
- `dev/check_address.py` —— 分别打印 `devicestatus` 与 `operate` 的 location，
  直观看清地址到底从哪来
- `dev/check_restart.py` —— 用真实接口走一遍「重启」时序，并**人工把
  `batteryInfo` / `signalInfo` 抹成空**复现限流响应，与「无缓存」做对照
- `dev/ha_probe.py` —— 读线上 HA 的实体属性与日志，并判断装的是不是新版代码
- `dev/dump_status.py` —— 打印原始响应，接口变更时用

> `operate` 有限流，所以 `test_api.py` 里撞限流算 **SKIP 而不是 FAIL**。

> ⚠️ 写测试时注意：`dev/_loader.py` 的 `make_status(desc=None)` **默认不给地址**，
> 这是**故意的** —— 真实 `devicestatus` 就不给。以前那里默认塞了一个地址，
> 直接把「首轮跳过定位 → 地址变空」这个 bug 掩盖过去了，别改回去。

---

## 已知限制

- 只有 vivo / iQOO 账号能用（走的是 vivo 云服务私有接口）
- 依赖非官方接口，vivo 侧改动可能导致失效，需要更新解析逻辑
- 定位精度取决于 vivo 返回的 `radius`（实测约 40 米）
- 设备关机 / 未开启查找功能时拿不到新坐标，只能显示最后一次位置
- **地址依赖定位指令**：地址（`locationDesc`）只随「下发定位指令并成功」返回。
  关掉定位开关、或长期被限流时，地址不会更新（也不会被清空）
- 坐标系结论（BD-09）是在武汉实测得出的（文中出现的坐标均为脱敏后的公开地标示例），
  接口内部没有坐标系标识字段。如果哪天位置又开始偏，跑 `dev/check_crs.py` 重新判定，
  改配置即可
- 定位指令受 vivo 限流约束，因此「实时性」的上限由限流决定，不是由轮询间隔决定 —— 
  把间隔调小并不会更快，反而更容易把接口撞进限流

## 致谢

接口调用顺序参考了吾爱破解论坛 [凌帝] 的 VIVO 设备位置监控脚本
（52pojie.cn/thread-2048559-1-1.html）。本集成是把它重写为
Home Assistant 原生集成，并修掉了原脚本中若干实测发现的问题。
