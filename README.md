# 手机遥控台

在电脑网页上点一个按钮，通过 USB 自动操控安卓手机，一键触发各种「重要日卡片」场景。
左侧是场景目录（可搜索 / 筛选 / 折叠），中间调参数并运行，右侧看手机实时画面；
新增场景沿用同一套逻辑，加到 30+ 种也仍有条理。

**生日祝福卡片**（greeting）

1. 首次运行在「今天 + 1」建一个 fixture 测试事件（走一次日历 UI）
2. 之后只更新 fixture 的姓名/日期，不打开日历
3. 直接设置系统时间到生日当天，息屏等待、亮屏、截图锁屏卡片

**生日策划案卡片**（birthday）

1. 首次运行在「今天 + N 天」建一个 fixture「重要日 · 生日」事件
2. 之后只更新 fixture 的姓名/日期，不打开日历
3. 直接设置系统时间到生日前 3 天，息屏、亮屏
4. 锁屏出现「xx·生日 · 3 天后」策划案卡片

**起床闹钟延迟卡片**（wake_alarm_delay · 时间管理）

1. 刷机后首次：系统时间调到周三 22:00，保持亮屏 10 分钟，生成正常使用/窗口数据
   （参数「刷机预热」，日常已有数据可设为 0；只设置时间，不做额外预热校验）
2. 通过系统 `SET_ALARM` intent 直接创建并启用每天 04:01 的闹钟（不打开时钟 App）
3. 系统时间调到周三 23:39，**息屏等待 60 秒**到 23:40，再亮屏
4. 23:40 截图锁屏；没看到卡片则解锁并展开通知栏再确认一次

> 闹钟会留在手机里，如不再需要请在时钟 App 里关闭；反复测试可能累积同一时间的
> 闹钟，请定期清理。

**Mock 触发（三张时间管理卡片通用）**

三个时间管理场景的参数列表第一项都是「触发方式」，可选：

| 选项 | 行为 |
| --- | --- |
| 真实触发（改时间 + 建闹钟） | 上面各节描述的完整流程，会真的改系统时间、建闹钟、息屏等待 |
| Mock 触发（TransAtomicBrain 一键出卡） | 装测试 App → 点对应的 mock 按钮 → 回桌面即出卡，**不改系统时间、不建闹钟、不息屏等待** |

Mock 触发对应关系：

| 场景 | Mock 按钮 | 卡片 |
| --- | --- | --- |
| 起床闹钟延迟 `wake_alarm_delay` | MOCK 睡得有点晚卡 | 睡得有点晚 / 要将 07:30 的闹钟延后吗？ |
| 提前打开提示 `alarm_early_prompt` | MOCK 工作日开闹卡 | 明天是工作日 / 要开启明天的闹钟吗？ |
| 提前关闭提示 `alarm_early_close` | MOCK 休息日关闹卡 | 明天休息日 / 要关闭明天的闹钟吗？ |

Mock 触发流程（`scenario_atomic_mock.py`）：

1. 检查 `com.transsion.atomicbrain` 是否已安装；未装则从网络共享装
   `\\10.205.4.20\Odc_Temp_File\archermind\zixin.mei\apk\TransAtomicBrain_full_signed.apk`
2. `am start -n com.transsion.atomicbrain/.debug.Test` 打开调试页
3. 按 resource-id 点击对应 mock 按钮（`btn_mock_early_wakeup_alarm_delay` /
   `btn_mock_early_alarm_open` / `btn_mock_early_alarm_dismissal`）
4. 唤醒 → 上滑解锁 → 回桌面，等待并截图确认卡片（最多 30 秒）

> 注意：点完 mock 后调试 App 仍在前台，且屏幕常常已经熄灭或上锁；直接按 HOME
> 只会落到通知栏黑图。脚本内部已按「唤醒 → 上滑解锁 → HOME」的顺序处理。
> 也可以命令行直接跑：`python scenario_atomic_mock.py delay|open|close`。

**提前打开提示卡片**（alarm_early_prompt · 时间管理）

1. 创建每天 **04:05** 闹钟，然后在时钟 App 列表里把每日闹钟**关闭**（保留闹钟行）
2. 系统时间调到周日 **19:09**
3. 先**息屏等待 60 秒**，再亮屏解锁并**保持亮屏等待 60 秒**
4. 之后桌面「智慧建议」出现
   「明天是工作日 / 要开启明天的闹钟吗？」
5. 截图 → 前端确认

> 智慧建议是轮播/按天触发的：第一次最容易看到这张卡，重复跑同一天可能轮播到
> 「17 XOS」「Folax」等其他建议；测试多次时建议清理时钟 App 里多余的 04:05 闹钟。

**提前关闭提示卡片**（alarm_early_close · 时间管理）

1. 创建每天 **04:05** 闹钟，并保持每日闹钟**开启**
2. 系统时间调到周五 **19:09**
3. 先**息屏等待 60 秒**，再亮屏解锁并**保持亮屏等待 60 秒**
4. 之后桌面「智慧建议」出现
   「明天是休息日 / 要关闭明天的闹钟吗？」
5. 截图 → 前端确认

**一键打车卡片**（one_tap_taxi · 生活服务卡片）

1. 触发前检查 **Yango**（`com.yandex.yango`）是否已安装
   - 已安装：直接继续
   - 未安装：从网络共享直接装
     `\\10.205.4.20\Odc_Temp_File\archermind\zixin.mei\apk\yango_full.apk`
     （329467629 字节，普通 APK）→ `adb install -r -t -d <路径>`
2. 任何时间发送 `AppSuggestEvent`，`app_list=["com.yandex.yango"]`
3. 桌面出现一键打车卡片 → 截图确认

**一键点餐卡片**（one_tap_food · 生活服务卡片）

1. 触发前检查 **foodpanda**（`com.global.foodpanda.android`）是否已安装
   - 已安装：直接继续
   - 未安装：从网络共享装
     `\\10.205.4.20\Odc_Temp_File\archermind\zixin.mei\apk\foodpanda.apk`
     （129913559 字节）。**这个文件是 XAPK**：内含 `manifest.json` +
     base `com.global.foodpanda.android.apk` + 19 个 `config.*.apk` 分包，
     **没有 AndroidManifest.xml**，所以 `adb install` 必然报
     `INSTALL_PARSE_FAILED_UNEXPECTED_EXCEPTION: ... AndroidManifest.xml`。
     脚本检测到 `manifest.json` 会自动解包到临时目录，按 base → ABI → 密度 →
     语言 的顺序，用 `adb install-multiple -r -t -d <20 个 apk>` 一次装完，装完删临时目录。
2. 午餐 **10:45~13:00**、晚餐 **17:00~19:00** 才会出现；场景会先把系统时间设到参数
   指定的窗口内时间
3. 发送 `AppSuggestEvent`，`app_list=["com.global.foodpanda.android"]`
4. 桌面出现一键点餐卡片 → 截图确认

> 安装全程只用网络共享上的安装包，不需要任何 Google 账号密码；后端装完用 `pm path`
> 校验，两个 App 都已在 X6765 上实测装好并成功触发卡片。
> 共享上的旧 `yango.apk`（195772416 字节）是上传中途截断的坏包，已被 `yango_full.apk` 取代。

**卫星通话卡片**（satellite_call · 玩机技巧卡片）

1. 前置检查：`getprop ro.tr_telephony.satellite.support` 必须输出 **1**，
   否则场景直接中止并提示「不支持卫星通话」
2. 确认 `settings get global satellite_mode_enabled` 为 **1**；不是 1 时自动置 1
3. 确认 `settings get global os_island_play_card_switch` 为 **1**（玩机技巧卡片开关）
4. `pm clear com.transsion.atomicbrain` 清理原子化模拟器
5. 先把系统时间设到 **09:58**，再断开 Wi-Fi / 数据 6 秒并重新连接
6. 把日期推到 **+3 天**、时间设为 **09:59**，保证从网络重连到 10:00 是 **>72h**
7. 回桌面保持亮屏，等待 **10:00** 正常触发
8. 桌面/锁屏出现卫星通话智慧建议卡片 → 截图确认

> 实机结论：X6766 上 support=1、satellite_mode_enabled=1、
> os_island_play_card_switch 原为 0 已置 1；清理 + 09:58 重连 + 日期 +3 天 +
> 10:00 后，桌面智慧建议仍显示「17 XOS」/「早上好·新闻晨报」，锁屏和通知栏
> 也没有卫星通话卡片。该卡片是桌面智慧建议，不是「玩机技巧」App 里的内容。
> X6765 的 support 为空，不满足条件 1。

**体验报告卡片**（monthly_summary / yearly_summary · 体验报告卡片）

1. 月度总结：目标时间 = **下个月的第二个周一 08:59**（例：11-04 → 12-14 08:59）
2. 年度总结：目标时间 = **当年 12 月 25 日 08:59**
3. 极速直设系统时间 → **息屏 60 秒** → 上滑解锁 → 等待 **90 秒**让卡片渲染 → 截图确认

**跨国 / 跨城卡片**（cross_region · 位置感知卡片）

`method` 可选四种：

| method | 做法 | 结果 |
|---|---|---|
| `mock_country` | 直接发 LocationEvent，`json_data={"country_code":"IN","city_code":""}` | 跨国卡片 |
| `mock_city_1148` | 同上，`city_code="1148"` | 跨城卡片 · 德里 |
| `mock_city_1057` | 同上，`city_code="1057"` | 跨城卡片 · 新德里 |
| `location` | 真实改定位：上海 (31.230416,121.473701) 亮屏 `wait_min` 分钟 → 新德里 (28.6139,77.209) 亮屏 `wait_min` 分钟 → 上滑回桌面 | 跨国 / 跨城卡片 |

- 发事件用 `am start-foreground-service -n <组件> -a core.intent.action.DISPATCH_EVENT`，
  组件由 `cmd package query-services --brief` 查出（XOS 17 的分块输出也认）
- `location` 路径用 test provider 打点：`appops set 2000 android:mock_location allow` →
  `add-test-provider gps` → `set-test-provider-location` → `set-test-provider-enabled gps true`
- 收尾必须**先 `remove-test-provider gps` 再重开一次定位开关**（`settings put secure location_mode`
  先 0 再恢复原值）。顺序反了会让 gps provider 变成「不是 test provider」，之后 add/remove
  全部失效，mock 坐标就永久留在 `dumpsys location` 里（X6765 实测）

## 界面

界面按「场景目录 / 工作台 / 实时画面」三块重做，场景数涨到 30+ 也不会挤：

- **场景目录**：搜索（`/` 或 `Ctrl+K`）、分组筛选、分组折叠、最近使用；
  窄屏（≤1280px）自动收成抽屉，点顶栏「场景目录」打开。
- **工作台**：选中场景 → 调参数 → 一键运行；运行时显示进度、用时、
  步骤序列和日志，可暂停 / 结束；底部参数条支持一键恢复默认。
- **实时画面**：自动刷新间隔可调，点击画面可放大；运行中显示 LIVE 扫描线；
  设备刚连上时会主动抓一帧，不用干等。
- **主题**：右上角切换「夜航」深色 / 「纸感」浅色，选择会记住。
- **快捷键**：`/` 或 `Ctrl+K` 搜场景，`↑/↓` 切换场景，`Ctrl+Enter` 运行，
  `Esc` 关闭抽屉 / 大图或清空搜索。
- **动效**：入场错峰、卡片悬浮、步骤盖章；确认/重试在右下角，成功/失败结算也是右下角小提示条，不遮全屏。

## 新增场景

在 `main.py` 的 `SCENARIOS` 里加一项即可，前端会自动出现在目录里，通常不用改
HTML / CSS / JS。除 `id / title / tag / desc / params / specs` 外，可按需加：

| 字段 | 作用 |
|---|---|
| `group` | 左侧目录分组名；不写则按 id 前缀推断 |
| `retryable` | 未触发时是否提供「下月同日重跑」；不写则节日场景 false、其余 true |
| `icon` | 卡片图标键：`cake` / `heart` / `exam` / `ticket` / `pin` / `lantern` / `spark` / `calendar` / `gift` / `star` / `moon` / `wave` / `flame` / `clock` / `car` / `food` / `satellite` |

分组会自动分配强调色；搜索、筛选、折叠、键盘切换都对新场景生效。

## 极速模式

旧流程的两个大头是「设置页改时间」和「日历 UI 建重要日」，每次都要多次
`uiautomator dump`（一次约 2.5s），遇到新弹窗还会中断。现在默认走极速路径：

1. **直设系统时间**：设备 shell 有 `SET_TIME` 时执行
   `settings put global auto_time 0` + `cmd alarm set-time <epoch_ms>`，
   实测约 **70ms**；设备不支持时自动回退到原来的设置页滚轮。设置前会先跳到
   前一天再跳回目标日，强制刷新锁屏卡片，避免同日期重复运行时看到旧卡。
2. **fixture 事件复用**：重要日类型存在 CalendarProvider 的
   `extendedproperties`（`ts_cal_event_type`），但系统只允许 sync adapter 写这张表，
   普通 App/shell 写不进去。所以每种类型首次仍走一次原日历 UI 建事件，随后在
   `fixtures.json` 里登记该事件；之后每次只 `content update` 它的
   `title / dtstart`（保留 duration、类型、提醒），不再打开日历。
3. **不启动日历、不校验焦点**：时间直设后再启动日历反而会引入弹窗和等待；
   实测锁屏卡片会自己响应 provider 时间变化。
4. **锁屏先行确认**：唤醒后保持亮屏，先截图锁屏卡片，再让前端确认，
   确认完才解锁（`wm dismiss-keyguard`，几十毫秒），截图/确认时卡片不会被滑走。
5. **等待默认 60 秒**：这台设备必须等 60 秒卡片才会生成，**不要调小**；
   参数范围 5~300 秒，保持默认 60 即可。极速路径省掉的是设置页/日历 UI
   的准备时间，60 秒的卡片生成等待无法省。
6. **重要日提醒不需要选类型**：`important_day`（无类型）首次 seed 时直接填名字，
   跳过类型下拉；fixture 按名称登记，后续同样只更新标题和日期。

首次运行每种卡片类型会走一次原 UI 建 fixture，**这一次是慢的**；登记成功后
后续都走极速更新。`fixtures.json` 按设备串号保存，多设备互不影响。

想一次把全部重要日类型都预置好（每种类型首轮仍会打开一次日历），可运行：

```bash
python seed_important_days.py
```

会依次处理生日、纪念日、考试日、观演日、重要日提醒；已有 fixture 的类型自动跳过。
之后这些类型的卡片设置名字/日期都不再打开日历。

想重置某台设备的 fixture，删掉 `fixtures.json` 对应条目即可；

```bash
python -c "import fixtures; fixtures.clear()"
```

会清空所有设备的登记，下次运行重新走 UI 建 fixture。

如果新的极速路径在某个特殊机型/系统上不工作，可设置
`PHONE_REMOTE_LEGACY=1` 临时回到旧的祝福卡片查找/复用流程；策划案卡片则删掉
`fixtures.json` 重新 seed。

## 启动

```
cd phone-remote
python main.py
```

会自动打开浏览器到 <http://127.0.0.1:8765>，点「一键运行」即可。

`python main.py --port 9000` 换端口，`--no-open` 不自动开浏览器，
`--scrcpy <路径>` 手动指定 scrcpy.exe。
若端口已被占用（说明已有一个实例在跑），会提示并直接打开那个地址。

## 依赖

- Python 3.12（仅此一项需要已安装）
- adbutils、Pillow（`pip install adbutils pillow`，本机已装）
- 手机：开发者选项 → USB 调试开启，插线后在弹窗点「允许」

零 pip 新装、零构建工具；uiautomator2 因 Android 17 兼容问题未使用，
控件定位走平台自带 `uiautomator dump`。

## 文件

| 文件 | 职责 |
|---|---|
| `phone_ctl.py` | 设备控制层：dump 解析、控件查找、点击/滑动/滚轮闭环 |
| `fast_clock.py` | 极速系统时间：`cmd alarm set-time`，带权限探测、校验和旧界面回退 |
| `fixtures.py` | fixture 事件登记 / 更新；`fixtures.json` 按设备串号保存 |
| `scenario_birthday.py` | 策划案场景 + fixture 快路径 + 可复用动作库（唤屏/选日期/建生日/改系统时间/息屏解锁） |
| `scenario_greeting.py` | 祝福卡片场景：fixture 快路径 + 旧流程兼容，`PHONE_REMOTE_LEGACY=1` 可切回旧查找/复用逻辑 |
| `scenario_alarm.py` | 起床闹钟延迟：10 分钟预热 + SET_ALARM 每日闹钟 + 周三 23:39 亮屏等待卡片 |
| `scenario_alarm_prompt.py` | 提前打开提示：关闭每天 04:05 闹钟 + 周日 19:09 桌面等待 |
| `scenario_alarm_close.py` | 提前关闭提示：保持每天 04:05 闹钟开启 + 周五 19:09 桌面等待 |
| `scenario_app_suggest.py` | 生活服务：一键打车（Yango）/ 一键点餐（foodpanda）；共享路径装包，XAPK 自动拆包 install-multiple |
| `scenario_satellite.py` | 玩机技巧：卫星通话卡片，支持检查 + 清原子化模拟器 + 断网重连 + 3 天/10:00 |
| `scenario_summary_report.py` | 体验报告：月度总结（下月第二个周一 08:59）/ 年度总结（当年 12-25 08:59） |
| `scenario_cross_region.py` | 位置感知：跨国 / 跨城卡片（LocationEvent 直发，或上海→新德里定位切换） |
| `seed_important_days.py` | 一次性预置生日/纪念日/考试/观演日/重要日五类 fixture |
| `main.py` | 入口：零依赖 Web 后端（**只绑 127.0.0.1**）+ 场景注册表 + 自动开浏览器 |
| `web/` | 前端三件套（场景目录 + 工作台 + 实时画面，深浅双主题） |
| `fixtures.json` | 设备 fixture 登记（首次 seed 后自动生成；可删除重置） |

## 性能

极速路径实测（Windows + adb over USB，Infinix X6765 / Android 17）：

| 阶段 | 耗时 |
|---|---|
| fixture 查询 + 标题/日期更新 | ~3~5s |
| 直设系统时间 | ~0.1s |
| 息屏等待 | **默认 60s（卡片生成必需，不要调小）** |
| 唤醒 + 截图 + 确认 + 解锁 | ~5~8s |
| **单轮总计** | **约 70~85s** |
| 首次 seed（走一次日历 UI + 60s 等待） | 约 2 分钟，仅一次 |

旧路径需要设置页滚轮 + 日历 UI 建事件，通常 2 分钟以上，且新弹窗会让整轮失败；
极速路径不再依赖日历/设置 UI，弹窗基本不再出现在关键路径上。60 秒卡片等待
本身保留，省掉的是前面几十秒的 UI 准备和设置页操作。

历史 dump 成本（Windows + adb over USB，Infinix X6878）：

| 操作 | 耗时 |
|---|---|
| `uiautomator dump`（拿控件树） | **~2400ms** ← 唯一的大头 |
| `input tap` / `keyevent` | ~140ms |
| `dumpsys window \| grep mCurrentFocus` | ~170ms |
| `screenshot` | ~500ms |

dump 慢是因为每次都要在设备侧起一个 JVM，换 `--compressed` 或写文件再读都无效。
所以提速思路是**少 dump**，而不是把单次 dump 变快：

1. 切 Activity 时先用 ~170ms 的**焦点轮询**（`wait_focus`）等窗口出现，再 dump 一次；
2. `wait_nodes` 在"命中那一次 dump"里把整棵树带回来给后续 `find` 复用，
   `settle` 让常见情况只需一次 dump（旧写法是"dump 失败→再 dump"，每次白等 2.4s）；
3. 关弹窗、读 `img_right`、读 `text_title` 等全部复用已有控件树；
4. 滚轮闭环每轮滑 10 格（旧版 5 格 + 每轮 sleep 0.6s），日/分钟滚轮从 6 轮降到 1-3 轮；
5. 三个日期滚轮 + 两个时间滚轮改成**一次 dump 读全部、批量收敛**（`set_wheels`），
   并复用 `wait_nodes` 已抓好的树做首轮读取，滚轮段落 dump 次数近乎砍半；
6. 解锁轮询把锁屏与焦点查询合并成一次 `dumpsys`（`window_info`），每次省 ~0.17s；
7. 砍掉几十处固定 `sleep`（2.5s/2s/1.5s），改成"短沉降 + 命中即走"；
8. `wm size`、设备型号缓存一次，避免整条流程反复往返。

## 注意

- **设备自动重连**：后端每次查询都实时枚举 adb（不缓存），拔插/换机后前端
  3~5 秒内自动识别到新设备，无需重启服务；顶栏设备状态一栏是按钮，可点击立即重测。
  检测不到时若 adb 卡死会自动 `start-server` / 必要时 `kill-server` 恢复，前端会在
  断开/恢复切换时提示一次
- **fixture 是可修改的测试事件**：每种卡片类型只有一个 fixture，每次运行会改它的
  姓名和日期；不要把它改成你自己的真实日历事件。`fixtures.json` 按设备串号隔离，
  删掉即可重新 seed
- **日历 extendedproperties 写保护**：重要日类型不能通过普通 content insert 新建，
  所以本工具采用「一次 UI seed + 后续更新 fixture」；如果某系统连 provider 更新
  也不刷新卡片，请把该类型用旧 UI 路径跑一次，或反馈场景日志
- **姓名仅支持 ASCII**（`input text` 不支持中文；中文需装 ADBKeyboard）
- 日期以**手机时钟**为基准计算（场景本身会改手机时间，两个时钟会错位）
- **日历视图会自动收敛**：停在「我的课表」子页会自动按返回键回到主界面；
  停在年视图（`dateTitle` 是 `2026` 这种年份）会自动点「{年}年{月}月」格子下钻到月视图。
  两者都不成立时才报错并提示手动切换。
- 运行期间脚本会临时开 `svc power stayon usb` 防止息屏；结束后保持亮屏方便查看
  卡片现场，可在手机设置或重新拔插后手动关闭常亮
- 想要 60fps 实时画面：用 scrcpy。程序会自动在 PATH、已知路径
  （如 `D:\APPS\scrcpy-win64-*\scrcpy.exe`、`D:\tools\scrcpy\`）以及常见目录下查找；
  也可用 `python main.py --scrcpy <路径>` 或环境变量 `SCRCPY_PATH` 指定
- 结束后手机时间停留在过去，需要手动把「自动设置时间」开关打开恢复
