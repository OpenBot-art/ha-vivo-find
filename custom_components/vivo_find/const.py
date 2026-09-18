"""VIVO 查找设备 - 常量定义。"""

DOMAIN = "vivo_find"

# 配置项
CONF_COOKIE = "cookie"
CONF_DEVICE_NAME = "device_name"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_LOCATE_ON_UPDATE = "locate_on_update"
CONF_SOURCE_CRS = "source_crs"
CONF_TARGET_CRS = "target_crs"

# 配置流程校验时解析到的设备身份，写进 entry.data。
# 为什么必须持久化这几个字段：实体的 unique_id 与名称必须**稳定**，
# 不能依赖运行期数据 —— 否则首次刷新若拿不到 imei，unique_id 会退化成
# 兜底值，下一次刷新拿全了又变回真值，HA 会当成两个不同实体，
# 表现为「实体凭空多出一个、旧的变不可用」，用户配的卡片与自动化全部指错。
CONF_DEVICE_IMEI = "device_imei"
CONF_DEVICE_ALIAS = "device_alias"
CONF_DEVICE_MODEL = "device_model"
CONF_DEVICE_EMMCID = "device_emmc_id"

# 默认与边界
DEFAULT_SCAN_INTERVAL = 600
MIN_SCAN_INTERVAL = 60
MAX_SCAN_INTERVAL = 86400
DEFAULT_LOCATE_ON_UPDATE = True

# ---- 坐标系 ----
# 实测确认：vivo 接口返回 **BD-09（百度坐标）**，见 crs.py 顶部的完整判定依据。
# 这是本集成最容易踩的坑 —— 直接当 WGS84 用，地图上的点会偏约 1.2 公里。
DEFAULT_SOURCE_CRS = "bd09"
# HA 的 device_tracker 规范、zone/person 判定、默认 OSM 底图都是 WGS84，
# 所以默认转成 WGS84 输出。若用高德底图的自定义卡片，可改成 gcj02。
DEFAULT_TARGET_CRS = "wgs84"

# VIVO 接口轮询参数（定位指令下发后多久查一次 / 最多查几次）
POLLING_INTERVAL = 3
MAX_POLLING_TIMES = 15
REQUEST_TIMEOUT = 15

# 两次「下发定位指令」之间的最小间隔（秒）。
# 实测 operate 会被限流并返回「操作过于频繁」，且一次成功定位后会锁几分钟，
# 所以必须做冷却。默认轮询间隔 600 秒时基本不会触发。
LOCATE_COOLDOWN = 300
# 撞上限流后的冷却时间（实测几分钟后自动恢复）。
# 刻意取得比默认轮询间隔（600）短：若与间隔相等，下一轮的 now 会正好卡在
# 冷却边界上、因几秒抖动被判为「还没到点」而整轮跳过，白等一个周期。
LOCATE_RATE_LIMIT_COOLDOWN = 420

MANUFACTURER = "vivo"

PLATFORMS = ["device_tracker", "sensor"]

# 名称兜底：别名和 entry.title 都拿不到时用这个。
# （正常流程下 entry.title 一定有值，这里只是防止手工改 .storage 后炸掉）
FALLBACK_DEVICE_NAME = "VIVO 设备"


def resolve_device_name(entry) -> str:
    """决定实体的设备名称 —— **唯一**来源，device_tracker 与 sensor 共用。

    优先级刻意排成：别名 > entry.title > 兜底。

    为什么**不**回退到型号（`device_model`）：
      型号是产品线名，两台同型号的手机必然同名；别名是用户给这台机器起的
      名字，才具有唯一性。一旦用型号当名称，实体 ID 会变成
      `device_tracker.iqoo_neo10pro` 这种「看起来像设备名、其实是型号」的
      东西，既不符合用户预期，也无法区分同型号的两台设备。

    为什么只读 entry.data / entry.title，不读 coordinator.data：
      运行期数据会抖。首次刷新拿不到 alias 时名称退化成兜底值，下一轮又
      变回别名 —— HA 会认为这是两个不同实体，表现为「实体凭空多一个」。
      配置阶段固化的值才是稳定的。
    """
    return (
        (entry.data.get(CONF_DEVICE_ALIAS) or "").strip()
        or (entry.title or "").strip()
        or FALLBACK_DEVICE_NAME
    )

# ---- 服务 ----
# 手动立刻定位一次。给「想让地址/位置马上更新」的场景用，
# 比缩小轮询间隔安全得多（不绕过限流冷却）。
SERVICE_LOCATE_NOW = "locate_now"
ATTR_FORCE = "force"

# 定位结果状态码（透出到实体属性，回答「这次到底为什么没拿到地址」）
LOCATE_OK = "ok"
LOCATE_THROTTLED = "throttled"
LOCATE_TIMEOUT = "timeout"
LOCATE_FAILED = "failed"
LOCATE_SKIP_FIRST = "skipped_first_refresh"
LOCATE_SKIP_COOLDOWN = "skipped_cooldown"
LOCATE_SKIP_OFFLINE = "skipped_offline"
LOCATE_SKIP_DISABLED = "skipped_disabled"

# 上次成功数据的持久化（.storage/vivo_find.<entry_id>）。
# 目的：HA 重启 / 集成重载后第一轮刷新往往拿不全数据（详见 coordinator 注释），
# 有了缓存就立刻有电量、网络、位置可显示，不必干等一个轮询周期。
STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.last_data"

# 首次刷新（或重载后第一轮）允许的快速重试次数与间隔。
# 只用于「设备刚联网 / 时序抖动」这类秒级问题；vivo 的限流是分钟级的，
# 重试救不了，所以次数必须很小，避免把限流撞得更深。
FIRST_REFRESH_RETRIES = 2
RETRY_DELAY = 5
