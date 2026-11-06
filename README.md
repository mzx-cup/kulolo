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

**停电预警卡片**（power_outage_warning · 停电建议）

> 这一组需要 **root 版设备**（`adb shell id` 要是 `uid=0(root)`）。要向
> `com.transsion.tranradionet/.tce.TceService` 发 action，该服务受 `signature|privileged`
> 的 `START_TCE_SERVICE` 保护，普通 `shell` 用户会被拒。

流程（全程联网）：

1. 检查 root（不是 `uid=0(root)` 直接报错，别浪费后面几分钟）
2. 确认联网（ping `8.8.8.8`）
3. 时区改内罗毕、国家改 KE：`setprop persist.sys.timezone Africa/Nairobi` +
   `setprop persist.tr_oobe.country KE`
4. 先解锁回桌面 —— **`pm clear` 会清掉「今天首次解锁」标记，所以第一次解锁必须留给真正的触发**
5. **系统时间先调到目标日 11:49**（极速直设）——顺序很关键，见下面的「两个隐蔽前提」
6. 把 GPS mock 到内罗毕（`-1.286389, 36.817223`）—— 见下面的「两个隐蔽前提」
7. 注入内罗毕常住区证据（等价于 `设置常住区-0727.bat`，纯 adb 实现）：
   `pm grant` 定位权限 → `location_mode 3` → `SET_COUNTRY_OVERRIDE ke` →
   `RESET_COUNTY all` → 连灌 5 个已完成夜晚（前 1~5 天 23:00 EAT）的
   `INJECT_COUNTY_LOC --ef lat -1.286389 --ef lng 36.817223` → **补一个
   `time_ms=now` 的当前点位** → 等 10 秒 → `DUMP_COUNTY` 读
   `evidence dates=5` / `current points=N` → `QUERY_COUNTY --es business_id power_outage_alert`
8. `pm clear com.transsion.atomiccore` + `pm clear com.transsion.atomicbrain`
9. 息屏 60 秒 → 亮屏 → 上滑解锁 → 等卡片
10. `finally` 里还原 mock 定位（先 `remove-test-provider gps` 再 toggle `location_mode`，
    顺序反了 provider 会卡死）

**两个隐蔽前提（踩过坑，务必按这个顺序）**：

1. **证据日期是相对「设备当前日期」算的**。同样注入 `10-10~10-14` 这 5 夜，设备日期还在
   `11-05` 时 `DUMP` 也报 `evidence dates=5`，但 `TceCountyResidentMgr` 会说
   `resident=null/NONE`（夜里被 `cleanupExpiredGeoCache removed=2` 清掉了）。把设备时间拨到
   `10-15` 之后，**同样是这 5 夜**立刻变成 `resident=KE-30/HIGH`。所以必须先设时间再注入证据，
   反了就白跑。
2. **`dumpsys location` 的 last location 必须在内罗毕**。设备默认停在重庆
   （`last location=Location[network 29.677337,106.673920 ...]`），`resolveCounty` 会打
   `country mismatch profile=KE geocodeCountry=CN admin=Chong Qing Shi` →
   `status=COUNTY_RESOLVE_FAILED`，而且会写 **negative cache**
   （之后几次 `resolveCounty: negative cache hit` 都返回同一条），把注进去的 resident 证据整个丢掉。
   先 mock 到内罗毕（或至少补一个当前点位让 `current points>0`）才能让 GEO 反查落到 KE。

**真正的卡点不是清包、也不是时间，而是常住区（County Resident）**：

- 规则 `64379`（`AITIPS_Power_outage_warning`）的 5 条 ability 里 `29 = CONTAIN "KE"`
  要求常住区在肯尼亚。设备默认解析成 `recommendType=CURRENT, recommend=CN-CQ/重庆`，
  于是 `BlackoutIntent` 拿 `keywords=[重庆, CN-CQ]` 去查 KPLC，必然 `no matched outage`。
- **GPS mock 单独用不够，但它是必要的**：test provider 只改 `dumpsys location` 的
  `last location`，`TceCountyResidentMgr` 用的是自己 ingest 的「夜间证据」；可要是
  `last location` 停在重庆，`resolveCounty` 会因 `country mismatch` 写负缓存并把证据全丢。
  两个一起上才行：先 mock 到内罗毕，再灌 5 个夜晚。
- 注入完 5 个夜晚 + 当前点位后才变成 `recommendType=RESIDENT, recommend=KE-30/Nairobi`，
  `BlackoutIntent` 改成 `keywords=[Nairobi, KE-30]`，才查得到公告。

规则 64379（从 APK 的 `assets/rule/AITIPS_Power_outage.json` 解出）：

| ability | 条件 | 含义 |
|---|---|---|
| 1 | `EQUAL true` | 解锁触发 |
| 2 | `RANGE 08_00_00~23_59_59`（`time_type=DAY`） | 只在白天 8:00~23:59 |
| 36 | `EQUAL 1`（`after_hour=08`） | 当天 8 点后**第一次**解锁 |
| 29 | `CONTAIN "KE"` | 常住区必须在肯尼亚 |
| 22 | `EQUAL 1` | 每天最多 1 次 |

同族另外两张卡（同一 APK 目录、`conflict_group: kplc_power_outage_active`，都已实现，
见下面的「停电省电提醒卡片 / 停电恢复卡片」）：
`AITIPS_Power_outage_saving.json`（64380，abilities 33/29/51/31：时段 + KE + 未充电 + 电量 ≤49%）、
`AITIPS_Power_outage_restoration.json`（64381，abilities 33/29/21：时段 + KE + 60 分钟间隔）。

**目标日期为什么是 2026-10-15**：KPLC 接口只返回近几天数据，且按 `area` 精确匹配几乎全空
（`area=Nairobi` / `area=Kiambu` 都 `total:0`），卡片实际是按 `region` 里的 `Nairobi` 匹配。
扫过 60 天历史后，`2026-10-15` 的次日恰有一条 `region="NAIROBI REGION"` /
`area="PART OF PANGANI"` / `06:00~14:00 UTC` 的公告，正好显示成卡片上的「明天 / 09:00-17:00」。
可用日期还有 10-01、10-10~10-15、10-23~10-31、11-02~11-04、11-06。

**判定卡片出没出**：优先看桌面控件树里有没有「停电预警」；**如果第一屏被别的卡片
（实测英语环境下是 Premier League）占了**，就退一步查 logcat —— 按下面顺序找第一个命中的行，
**取最靠前的那个证据**（`handleGetTpkPackage, serviceId: 64379` 最干净；`remoteList:` 那种整行
会同时含早安卡，看着像别人出卡）：

1. `handleGetTpkPackage, serviceId: 64379` —— 原子化按这个 serviceId 去取 TPK
2. `generateCardView loadView call: 0-...AITIPS_Power_outage` —— 已经在建视图
3. `onShow ServiceInfo(...AITIPS_Power_outage)` —— 展示过
4. `displayMap: [0-...AITIPS_Power_outage` / 兜底 `AITIPS_Power_outage`

实测：中文在第 25 秒从控件树直接看到「停电预警」；英语第 4 秒就在桌面命中 `Outage Alert`；
阿拉伯语第 12 秒走 logcat 兜底判定为「已派发到智慧建议轮播」。

**停电省电提醒卡片**（power_outage_saving · 停电建议）

> 同样需要 **root 版设备**（要 `setprop persist.*`、`pm clear`、`dumpsys battery`）。

规则 64380（`AITIPS_Power_outage_saving`，与预警卡共用 intent，靠
`businessData.tvData.tvTitle` 区分）：

| ability | 条件 | 含义 |
|---|---|---|
| 33 | `EQUAL 0` | 时段触发（到点就触发） |
| 29 | `CONTAIN "KE"` | 常住区必须在肯尼亚 |
| 51 | `EQUAL false` | **不在充电** |
| 31 | `EQUAL 49` | **电量 ≤ 49%** |

流程（全程联网，用户 m08836 指定）：

1. 检查/安装 `TransAtomicBrain_full_signed.apk`（版本 17.11.00.104 起才有 KPLC debug 区）
2. 时区改内罗毕、国家改 KE
3. **系统时间先调到目标日 12:29**（见下面「日期框自动带当天」）
4. 先解锁回桌面 → `pm clear atomiccore` + `pm clear atomicbrain`
5. `am start -n com.transsion.atomicbrain/.debug.Test`，滑到底部的「KPLC 停电卡片 debug」区
6. 确认 `et_kplc_area = MATASIA`、`et_kplc_date = 目标日`（都是自动带出来的，**不要手输**）
7. `dumpsys battery set level 30` + `set status 1` + **`unplug`**（只 set status 1 不够，
   `usb powered` 仍是 true 时规则 51 不成立）→ 点「Mock 电量=30」
8. 点「查询 KPLC API」，等 `text_kplc_result` 出现公告（含「未查询到」直接报错）
9. 时间拨到 **12:30**（落在停电区间内）→ 息屏 10 秒 → 亮屏上滑解锁 → 出卡
10. `finally` 里 `dumpsys battery reset` —— **不还原会污染后面所有跟电量相关的判断**

默认目标日 **2026-09-18**、区域 **MATASIA**：KPLC 该日有一条
`area="MATASIA, OLOIKA, NKOROI"` / `05:30~14:00 UTC`（= 08:30~17:00 EAT）的公告，
12:30 在停电中、16:30 在结束前 2 小时。

**停电恢复卡片**（power_outage_restore · 停电建议）

规则 64381（`AITIPS_Power_outage_restoration`）：

| ability | 条件 | 含义 |
|---|---|---|
| 33 | `EQUAL 0` | 时段触发 |
| 29 | `CONTAIN "KE"` | 常住区必须在肯尼亚 |
| 21 | `SMALLER 60 MIN` | 两张恢复卡之间至少 60 分钟 |

流程与省电卡相同，区别只有三点：

1. **不 mock 电量**（规则 64381 根本不看电量/充电状态）；
2. 时间拨到 **16:30**（公告结束前 2 小时），而不是 12:30；
3. **进流程第一件事就 `dumpsys battery reset`**。三张停电卡同属
   `conflict_group: kplc_power_outage_active`，先到的会把后来的 DROP 掉。
   上一轮省电卡留下的电池 mock 是**持久的**（`dumpsys battery set` 会一直覆盖真实电量），
   不清就会让省电卡一直先出，日志里能看到
   `TAB.BlackoutIntent: sendIntent: blocked by conflict_group, scenario=RESTORATION`。

**两条真机上踩出来的通用前提**：

1. **先设系统时间，再 `am force-stop` + `am start` 重启调试 App**。KPLC 日期框的默认值取的是
   「设备当天」，这样日期就自动是 `2026-09-18`，**完全不用手输** —— 键盘一弹出整个 KPLC 区块
   会滚出屏幕（`dumpsys input_method` 里 `mServedView=null`），此后再按记住的坐标点第二个
   输入框必然点错（实测把日期写进了 area）。
2. **`dumpsys battery set` 是持久的**，只有 `dumpsys battery reset` 能还原。跑完必须 reset。

判定出卡：先看桌面控件树里的卡片文案（中 `省电建议` / `电力恢复时间`、英 `Save Power` /
`Power Restoration`、阿 `توفير الطاقة` / `استعادة الطاقة`）；第一屏被别的卡占位时退一步查
`logcat -d -s TpkServiceCardProvider:D` 里带 `tvTitle` 且含对应语言关键词的行。
**注意日志会截断长标题**（阿拉伯语 `توفير الطاقة` 打成 `توفير ال***`），所以 logcat 侧要用
短词（`توفير` / `استعادة`）而不是完整标题。

三种语言实测（X6765 root 版，每轮 17~18 步 `ok: true`）：
中文 `省电建议` / `电力恢复时间`、英语 `Save Power` / `Power Restoration`、
阿拉伯语 `توفير الطاقة` / `استعادة الطاقة`，全部在第 0 秒就从控件树命中。

## 回到桌面首页

卡片在锁屏、通知栏、桌面都能出，但**桌面首页**（有「智慧建议」卡片区的那一页）
才是要交付的最终界面。所以每次截图确认卡片之前，所有场景都会先执行一次
`ensure_home_before_confirm()`：

1. `Device.at_launcher_home()` 先看焦点窗口是不是 launcher（~170ms，非 launcher 直接返回 False）
2. 是 launcher 才 `uiautomator dump` 一次，按**首页专属控件**判定：
   `tc_time`（时钟 widget）/ `tc_date`（日期）/ `tv_temperature`（温度）任一存在，
   或出现文本「智慧建议」，即为首页
3. 不是首页就按 `KEYCODE_HOME` 回首页，最多 3 次，每次都重新判定

> 走弯路记录：`page_indicator`（`content-desc="主屏幕"`）在**每一页都存在且完全一样**，
> 不能用；`dumpsys activity com.transsion.launcher3` 里三页的 `TrCellLayout` 坐标也完全
> 一致，`TrWorkSpace` 上没有 `scrollX` / `mCurrentPage`；`dumpsys activity top` 更不含页信息。
> 最后只剩「首页专属控件是否存在」这一条可靠信号（X6766 / X6765 双机实测一致）。

列表页上按 HOME **一次**即回首页，重复按也不会翻页，所以这一步很便宜。
回首页失败只记日志、**不判失败**——锁屏/通知栏类卡片本来就回不到桌面首页。

**未出卡重试时会多清一次桌面**：前端点「未出卡，重试」或上一次运行失败再跑时，
除了原本的 `pm clear com.transsion.atomicbrain` 和 `com.transsion.atomiccore`，
还会执行 `adb shell pm clear com.transsion.launcher3`（`Device.clear_atomic_services()`
现在遍历 `LAUNCHER_PKG / ATOMIC_PKG / ATOMIC_CORE_PKG`），把残留的卡片状态彻底清掉。
launcher 被清后会自己重启，实测清完首页控件仍齐全、`at_launcher_home()` 仍为 True。

## 时间管理卡片先断网

`wake_alarm_delay` / `alarm_early_prompt` / `alarm_early_close` 三个场景的**第一步**
（真实触发和 Mock 触发都一样）都是断网：

- `svc wifi disable` + `svc data disable`，然后 ping `8.8.8.8` 轮询最多 10 次确认真的不通
- 跑完整条触发流程后，在 `finally` 里 `svc data enable` + `svc wifi enable` 恢复，
  并等待网络回来（保证失败/异常路径也不会把设备留在断网状态）

## 最近音乐卡片（BoomPlay）

`boomplay_recent_music`，分组 `BoomPlay`。按需求的做法拆成 7 步：

1. 频率控制校验（每天最多 2 次 / 触发后 2 小时冷却）
2. 需要时把系统时间往后拨（`2h` = 2 小时后，`next_day` = 隔天，`skip` = 不拨）
3. 进 Boomplay，随机播放一首歌约 10 秒
4. 回桌面，发 `AppSuggestEvent`（最近播放音乐卡片）
5. 打开系统蓝牙开关 + 发 `HEADSET_PLUG`（模拟连上蓝牙耳机，没有耳机也照发）
6. 等卡片出现，回桌面首页确认
7. 记账（`boomplay_music_state.json`，不入库、不进 git）

mock 投递是**双通道**的：

```bash
# 通道 1：需求给的原命令（要装 com.example.tpk.client/.RuleMockService）
adb shell am start-foreground-service --user 0 \
  -a "core.intent.action.DISPATCH_EVENT" \
  --es "data_type" "AppSuggestEvent" --es "action_type" "listener" \
  --es "json_data" '{"app_list":["com.afmobi.boomplayer"]}'

# 通道 2：通道 1 报 "Not found; no service started." 时自动改走 TransAtomicBrain
adb shell am start-service --user 0 \
  -n com.transsion.atomicbrain/.debug.DebugService \
  -a "brain.intent.action.DISPATCH_EVENT" \
  --es "data_type" "HEADSET_PLUG" --es "action_type" "listener" \
  --es "json_data" '{"state":1,"type":1}'
```

> 通道 2 **只能用 `am start-service`**。`am start-foreground-service` 会在 5 秒后抛
> `ForegroundServiceDidNotStartInTimeException: Context.startForegroundService()
> did not then call Service.startForeground()`，然后弹「Application Error:
> com.transsion.atomicbrain」把桌面焦点抢走（X6765 实测已复现）。

投递有没有送达，看 logcat 的 `TAB.DebugService: onAction:ACTION_DISPATCH_EVENT`。

### 出卡规则（已从规则引擎读出）

发一条 mock 事件后 `logcat` 会打印每条 rule 的每个 ability 判定，是唯一的真值来源。
这张卡对应 **`rule_id=10022`，开关 `atomic_switch_item_boomplayer_recent`**：

| ability | 类型 | 条件 |
|---|---|---|
| 9 | `AppSuggestAbility` | `values=[com.afmobi.boomplayer]`，`app_rank=2` → `app_list` 前 2 位里要有 boomplayer |
| 13 | `AppInstallCheckAbility` | 该包已安装 |
| 21 | `MinTimeIntervalAbility` | `type=HOUR, value=2` → 2 小时冷却 |
| 22 | `DayCountAbility` | `value=2` → 每天最多 2 次 |
| 25 | `PermissionCheckAbility` | `com.transsion.atomicbrain.action.BLUETOOTH` |

第 21、22 条正好就是需求里的频率控制（2 小时冷却 / 每天 2 次），代码里那套
`_freq_guard` / `_freq_record` 是跟它对齐的，改时间再触发的流程（2 小时后 / 隔天）
也是为了绕过这两条。

`app_rank=N` 的语义是「白名单 app 必须落在 `app_list` 的**前 N 位**」，
实测三种组合验证过：`["com.shazam.android"]`（size 1）match、
`["com.afmobi.boomplayer","com.shazam.android"]`（shazam 在 index 1）match、
`["boomplayer","boomplayer","com.shazam.android"]`（shazam 在 index 2）not match。

### 这张卡为什么还没出

两台机器上 `logcat` 都显示规则走完了 5 条 ability，但 `RuleManager` 仍判
`isRuleMatch AND not match:sb=9,13,21,22,25, ruleId=10022`，
而且**连 TransAtomicBrain 里官方的 `MOCK_APP_SUGGEST` 按钮也出不了这张卡**
（同一台机器上 `MOCK 睡得有点晚卡` 等闹钟 mock 是能出卡的，说明桌面出卡通路是好的）。

根因是 **`MinTimeIntervalAbility` 恒打印 `formatStr=1970-01-01 03_00_00`**，
即时间戳 0 —— 这张卡是「**最近**播放音乐」，必须先有真实的播放记录喂给规则引擎，
而 Boomplay 在本机永远 `error_tx`「无网络连接」、`music_name`「未知」、
`dumpsys media_session` 里 `state=STOPPED(1)`；设备本身 `wifi_on=1`、
`ping 8.8.8.8` 通、连 AdMob 广告都加载得出来，所以是 **Boomplay 自己的接口被墙 /
地区限制**，产不出播放记录。

也就是说：命令发对了、规则也读明白了，**卡在「Boomplay 播不了歌」这一环**。
换一台能正常播歌的机器（或给 Boomplay 通上它自己的服务），这张卡应该就能出来。

## 智能路况卡片（两条路径）

`smart_traffic`，分组 `路况天气`。这张卡有**两种触发方式**，用参数 `触发方式` 切换。

出卡规则 **`rule_id=10058`**（`assets/rule/SMART_TRAFFIC.json`，
`intent_id=transsion.intent.aitips.AITIPS_Road_conditions`）：

| ability | 类型 | 条件 |
|---|---|---|
| 2 | 时间窗 | `RANGE 00_00_00 ~ 11_59_59`，`extra={"time_type":"DAY","time_source":"dismiss_latch"}` —— **看末次闹钟 dismiss 的时刻，不看当前时间** |
| 22 | 日频控 | `EQUAL Int "1"`，key = `YYYY-MM-DD-10058`，每天 1 次 |
| 44 | 路况 latch | `EQUAL Boolean "true"`（active ability，智能路况触发闩） |
| 45 | 异常天气记忆 | `EQUAL Boolean "true"`（记忆里的今天要有白名单内的异常天气） |

异常天气白名单是 **`[7, 10, 12, 15]`**（对应 `TYPE_HEAVY_RAIN` 暴雨 / `TYPE_HIGH_TEMPERATURE` 高温 /
`TYPE_MODERATE_RAIN` 中雨 / `TYPE_STRONG_WIND` 大风），**硬编码在 App 里，改不了**。

### mock 路径（默认，稳定可用）

全程只动 test brain 调试页，不依赖真实天气：

1. 检查/安装 `TransAtomicBrain_full_signed(5).apk`（**必须这个包**：17.11.00.104 的调试页
   没有智能路况按钮，代码里靠 `versionCode >= 171000000` 判断，低了会覆盖安装）
2. 确认联网（`svc wifi enable` + ping 8.8.8.8，不动时区/国家）
3. `am force-stop` + `am start -n com.transsion.atomicbrain/.debug.Test`，滚到页面最底部的
   「智能路况」区
4. **先点「清理智能路况当日计数」** —— ability 22 一天只给 1 次，不先清后面评规则必 fail
5. 再点「MOCK 智能路况卡」，它会写异常天气记忆 + arm 末闹 dismiss 时刻 + 触发评规则
6. 回桌面，智慧建议出现「智能路况」

mock 按钮返回的文本会直接把四条 ability 的自检结论打出来，例如：
`天气快照已写入 WEATHER：date=2026-11-06 abnormalWeatherType=7(暴雨)，回读判定=true` /
`已 arm dismiss_latch=2026-11-06 08:30:00` / `今天(2026-11-06) abnormalWeatherType=7 ∈ 白名单，白名单=[7, 10, 12, 15]`。
实测三语言全通：中文 `智能路况` / 英语 `Smart Traffic` / 阿拉伯语 `حركة المرور الذكية`。

### real 路径（不碰 test brain）

按需求给的 6 步走，**全程不打开调试页**：

1. 检查/安装同一个 APK
2. 打开天气 App 并下拉刷新一次（首次会依次弹 GDPR「同意」页和系统定位授权页，自动点掉）
3. 系统时间调到当天 12 点前（默认 11:28）
4. `logcat` 查 `WeatherMemorySimulator|isAbnormalFromMemory|ingest normalized.*weather|SmartTrafficWeatherJudge`
5. 发 `am startservice -n com.transsion.atomicbrain/.debug.DebugService -a brain.intent.action.DISPATCH_EVENT --es action_type simulate_weather_memory --es target_date <设备当天> --ei abnormal_type 7`
6. 设「当前时间 + 1 分钟」闹钟 → 息屏等响 → 关闹钟 → 解锁回桌面

> 闹钟时间必须**现读设备时钟**再 +1 分钟。用流程开始时算好的时刻会落在过去
> （开天气 App + 刷新的耗时会让它过期），时钟会把它排到第二天。

**这条路径在本版本 App 上出不了卡，原因是三件独立的事实**（都已实测确认）：

- **`simulate_weather_memory` 这个 action 在 17.10.00.101 里根本不存在**。
  `DebugService` 收到会打 `E TAB.RuleActionHandler: handleTestDataAction: unknown action_type=simulate_weather_memory`。
  全 dex 扫 `simulate` / `weather_memory` / `abnormal_type` / `target_date` 都是 0 命中；
  本地 6 个 atomicbrain APK（含共享路径两个）全扫也都是 0 命中。
- **`action_type` 的合法值其实是 `handleTestDataAction` 的分支名**（`listener` / `memory` /
  `mock_json` / `percept` / `query`），而且**参数名必须是驼峰 `dataType` / `jsonData`**
  （写成 `data_type` / `json_data` 会得到 `dataType=null`）。四条分支都试过：
  `memory` 能写进 MemGov（`saveLatestData:type=WEATHER`）但自检读的是 MMKV 的
  `WEATHER_CHANGE_value`；`mock_json` 对 38 个候选 dataType 全部 `createTestEvent unkown type`；
  `percept` 报 `unsupported type`；`query` 报 `failed to set test data`。
- **真实天气接口不下发「今天」的 `abnormalWeatherType`**。`brain_SP` 里
  `WEATHER_CHANGE_value` 的 `days[]` 只在**未来某一天**偶尔带
  `abnormalWeather: {abnormalWeatherType: 17}`（17 = 毛毛雨，**不在白名单**），
  今天那条永远是 null。把设备日期拨到那天再开天气 App，自检确实读到
  `今天(2026-11-07) abnormalWeatherType=17 ∉ 白名单` —— 证明读的就是「今天」那条，
  但 17 出不了卡。换城市也没用：这台机器的天气 App 位置固定在「两江新区」，
  把 gps / fused / network 三个 provider 全 mock 成迪拜也不变。

所以 real 路径的代码是**按需求原样实现的**（流程 14 步全跑通、闹钟会响会被关掉），
但卡片出不来，`summary` 里会如实写「该版本不认识这个 action / 桌面上没有等到卡片」。
要让这条路径真的出卡，需要一个**含 `simulate_weather_memory` 分支的新版 APK**，
或者改成「mock 路径写天气记忆 + real 路径的闹钟 dismiss」的组合。

### 调试页的坑

- **`uiautomator dump /dev/tty` 在这台 X6766 / Android 17 上写出 XML 但不退出**，
  `adb shell` 会永久挂住。`Device.dump()` 现在首次探测 4 秒，超时就自动切「落盘式
  dump」（写到 `/data/local/tmp/_dsh_dump.xml` 再 `cat` 回来），之后整轮都走落盘。
- **调试页输入框一碰键盘就糟**：键盘弹起会让整块区域滚出屏幕（`mServedView=null`），
  之后按记的坐标点第二个框必定点错。改输入框后必须 `input keyevent 111` 收键盘再重新 dump。
- **设备的灭屏超时很短**：滚十几轮 swipe 走完可能自己黑屏，黑屏后 dump 直接报
  「控件树为空」。所以每轮滚屏、每次点按钮前都会先 `_ensure_awake()`（唤醒 + 解锁）。
- **装包会弹 Google Play 保护机制**（`PlayProtectDialogsActivity`），三个按钮是
  「发现未知应用时一律发送 / 本次发送 / **不发送**」，要点「不发送」，否则焦点被抢走。

## 界面

界面按「场景目录 / 工作台 / 实时画面」三块重做，场景数涨到 30+ 也不会挤：

- **场景目录**：搜索（`/` 或 `Ctrl+K`）、分组筛选、分组折叠、最近使用；
  窄屏（≤1280px）自动收成抽屉，点顶栏「场景目录」打开。
- **工作台**：选中场景 → 调参数 → 一键运行；运行时显示进度、用时、
  步骤序列和日志，可暂停 / 结束；底部参数条支持一键恢复默认。
- **实时画面**：自动刷新间隔可调，点击画面可放大；运行中显示 LIVE 扫描线；
  设备刚连上时会主动抓一帧，不用干等。
- **主题**：右上角切换「夜航」深色 / 「纸感」浅色，选择会记住。
- **设备胶囊**：顶栏只显示机型（如 `Infinix X6766`），串号放在 tooltip 里；
  接了两台以上时右侧出现可点的切换 chip，同样只显示机型。
- **快捷键**：`/` 或 `Ctrl+K` 搜场景，`↑/↓` 切换场景，`Ctrl+Enter` 运行，
  `Esc` 关闭抽屉 / 大图或清空搜索。
- **动效**：入场错峰、卡片悬浮、步骤盖章；确认/重试在右下角，成功/失败结算也是右下角小提示条，不遮全屏。
- **下拉菜单**：参数里的「下拉选项」是自绘的 listbox（`SelectMenu.vue`），
  不再用浏览器原生 `<select>`——原生的**选项浮层**由浏览器/系统绘制，CSS 够不着，
  永远是白底系统字体。自绘后触发器、浮层、圆角、高亮、hover、Esc 关闭、
  点外面关闭全部跟着主题走（深色「夜航」/ 浅色「纸感」都核对过计算样式）。

## 触发语言（中文 / 英语 / 阿拉伯语）

每个场景的参数末尾都有一个「触发语言」下拉：

| 选项 | 首选 tag | 实测落到 |
| --- | --- | --- |
| 中文 | `zh-Hans-CN` | `zh-Hans-CN` |
| 英语 | `en-US` | `en-US` |
| 阿拉伯语 | `ar-SA` | `ar-EG`（这台机器没编译 ar-SA） |

选中的语言和手机当前语言不同时，**开跑前会先把系统语言切过去，不需要重启手机**：

```bash
adb shell cmd locale set-device-locale ar-EG     # 2~3 秒后整机界面就换语言
adb shell settings put system system_locales "ar-EG,zh-Hans-CN,en-GB,en-US"
```

`cmd locale set-device-locale` 是 Android 13+ 的 shell 命令，走 LocaleManager 的
服务端接口，当场生效。它会把 `system_locales` 这个**语言列表**砸成单值，所以切完
再把原列表补回去（首选语言排第一）——这步不影响已经生效的界面语言，只是把用户
配的其它语言还原，下次开机也还是这个首选。

两个实机坑：

- **语言 tag 是枚举出来的**，不能凭空写。`cmd locale list-device-locales` 才能
  知道这台机器支持什么：X6766 有 `ar-EG`、**没有 `ar-SA`**（写 `ar-SA` 会直接
  `Error: Invalid locale tag`）。所以代码里有一张同语言候选表，按支持列表挑。
- 极少数机器（Android 12 及更早）没有 `cmd locale`，此时自动退回
  「写 `system_locales` + 整机重启」的老路，逻辑同样保留着。

已经一致就直接跳过，不会白切。切换失败（拔线、超时等）只记一条提示，仍按当前
语言把流程跑完，不会因为语言这一步把整轮废掉。

三套语言下 26 个场景都做过真机全量回归（Infinix X6766 / Android 17）：
阿拉伯语 26/26、英语 26/26 通过。**停电建议的三张卡是这台机器换成 root 版 X6765 之后
新增的第 27~29 个场景，中文 / 英语 / 阿拉伯语下也都逐张真机跑通过。
智能路况是第 30 个场景，mock 路径三语言都通过；real 路径的流程也三语言跑通，
但本版 App 出不了卡（原因见上一节）。**

多语言下踩到并修掉的坑：

- **阿拉伯-印度数字**：`١٦` `٠٩:٤٦` 这类数字不是 ASCII，所有读文本再比数字的地方
  都要先过 `locale_kit.to_ascii_digits()`（日期格、`dumpsys alarm` 的
  `triggerTime`、设置页日期摘要都会变）。
- **RTL 翻转方向**：阿拉伯语下日历左滑是**上一个月**、右滑才是下一个月；
  控件也是镜像的（日历「添加」FAB 跑到左下角，闹钟开关跑到左侧）。
  换月统一走 `scenario_birthday._swipe_month()`，按 `system_locales` 判 RTL 再翻。
- **文案要三语齐全**：`locale_kit.UI_LABELS` 里存着「自动设置时间 / 日期 / 时间 /
  确定 / 弹窗按钮 / 重要日 / 各类型名」等中英阿三套写法；判断「是不是同一个标签」
  时用**包含匹配并取最短文本**——阿拉伯语的「时间」`الوقت` 是「自动设置时间」
  `تعيين الوقت تلقائيًا` 的子串，按控件顺序取第一个会错点自动时间那一行。
- **别靠截图找颜色**：闹钟开关改成按控件树的 `onoff` rid + 同行 `digital_clock`
  文本定位，不再扫橙色像素（RTL 下开关在左边，扫右边一个都找不到）。
- **`uiautomator dump` 会失败**：时钟 App 列表每秒刷倒计时，`dump` 报
  `could not get idle state`；现在 `Device.dump()` 会重试并改走 `--compressed`。

## 新增场景

在 `main.py` 的 `SCENARIOS` 里加一项即可，前端会自动出现在目录里，通常不用改
HTML / CSS / JS。除 `id / title / tag / desc / params / specs` 外，可按需加：

| 字段 | 作用 |
|---|---|
| `group` | 左侧目录分组名；不写则按 id 前缀推断 |
| `retryable` | 未触发时是否提供「下月同日重跑」；不写则节日场景 false、其余 true |
| `icon` | 卡片图标键：`cake` / `heart` / `exam` / `ticket` / `pin` / `lantern` / `spark` / `calendar` / `gift` / `star` / `moon` / `wave` / `flame` / `clock` / `car` / `food` / `satellite` / `music` |

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

## 打包成 exe

```
python build_exe.py
```

产物是 `dist/手机遥控台.exe`（单文件，双击即用，目标机不需要装 Python）。

图标取自 `assets/app.ico`（库洛米，9 个尺寸 16~256）；想换图标就把新图存成
`assets/icon-source.jpg` 后跑 `python tools/make_icon.py` 重新生成。

## 依赖

- Python 3.12（仅此一项需要已安装）
- adbutils、Pillow（`pip install adbutils pillow`，本机已装）
- 手机：开发者选项 → USB 调试开启，插线后在弹窗点「允许」

零 pip 新装；uiautomator2 因 Android 17 兼容问题未使用，
控件定位走平台自带 `uiautomator dump`。

**只想用不改前端的话，不需要 Node**：`web/` 里已经是构建好的产物，
`python main.py` 直接打开就能用。只有改前端界面时才需要 Node 20+：

```bash
cd web-src
npm install       # 首次
npm run build     # 类型检查（vue-tsc）+ 打包，产物直接写进 ../web/
npm run dev       # 可选：热更新调试，5273 端口，/api 自动代理到 8765
```

前端技术栈：Vue 3 + TypeScript + SCSS + Vite。样式由原来的单个
`style.css`（2600+ 行）拆成 `web-src/src/styles/` 下的 17 个 partial，
视觉与原版逐像素一致；逻辑按职责拆到 `src/actions/`（目录、运行、设备、
截图、主题、会话）与 `src/stores/core.ts`（唯一一份响应式状态）。

## 文件

| 文件 | 职责 |
|---|---|
| `phone_ctl.py` | 设备控制层：dump 解析、控件查找、点击/滑动/滚轮闭环、桌面首页判定与回首页、清原子化服务 |
| `fast_clock.py` | 极速系统时间：`cmd alarm set-time`，带权限探测、校验和旧界面回退 |
| `fixtures.py` | fixture 事件登记 / 更新；`fixtures.json` 按设备串号保存 |
| `scenario_birthday.py` | 策划案场景 + fixture 快路径 + 可复用动作库（唤屏/选日期/建生日/改系统时间/息屏解锁） |
| `scenario_greeting.py` | 祝福卡片场景：fixture 快路径 + 旧流程兼容，`PHONE_REMOTE_LEGACY=1` 可切回旧查找/复用逻辑 |
| `scenario_alarm.py` | 起床闹钟延迟：先断网 + 10 分钟预热 + SET_ALARM 每日闹钟 + 周三 23:39 亮屏等待卡片；支持 Mock 触发 |
| `scenario_alarm_prompt.py` | 提前打开提示：先断网 + 关闭每天 04:05 闹钟 + 周日 19:09 桌面等待；支持 Mock 触发 |
| `scenario_alarm_close.py` | 提前关闭提示：先断网 + 保持每天 04:05 闹钟开启 + 周五 19:09 桌面等待；支持 Mock 触发 |
| `scenario_atomic_mock.py` | Mock 触发：装 TransAtomicBrain → 点 mock 按钮 → 回桌面出卡（不改时间、不建闹钟） |
| `scenario_app_suggest.py` | 生活服务：一键打车（Yango）/ 一键点餐（foodpanda）；共享路径装包，XAPK 自动拆包 install-multiple |
| `scenario_satellite.py` | 玩机技巧：卫星通话卡片，支持检查 + 清原子化模拟器 + 断网重连 + 3 天/10:00 |
| `scenario_summary_report.py` | 体验报告：月度总结（下月第二个周一 08:59）/ 年度总结（当年 12-25 08:59） |
| `scenario_cross_region.py` | 位置感知：跨国 / 跨城卡片（LocationEvent 直发，或上海→新德里定位切换） |
| `scenario_power_outage.py` | 停电建议：停电预警卡片（**需 root**；注入内罗毕常住区 → 清原子化 → 目标日 11:49 → 息屏 60s → 解锁出卡） |
| `scenario_power_saving.py` | 停电建议：停电省电提醒卡片（**需 root**；mock 电量 30% + KPLC 查公告 → 时间 12:30 → 息屏 10s → 解锁出卡） |
| `scenario_power_restore.py` | 停电建议：停电恢复卡片（**需 root**；先清电池 mock 避免 conflict_group 抢卡 → KPLC 查公告 → 时间 16:30 → 息屏 10s → 解锁出卡） |
| `scenario_smart_traffic.py` | 路况天气：智能路况卡片（mock = 清当日计数 + mock 按钮；real = 天气 App + 12 点前 + 1 分钟后闹钟，全程不碰 test brain） |
| `locale_kit.py` | 三语词表与解析：月份/星期/阿拉伯-印度数字归一化、日期格候选、UI 标签表、RTL 方向判定 |
| `locale_switch.py` | 触发语言切换：`cmd locale set-device-locale` 即时生效（不重启），并还原语言列表；老系统退回重启路径 |
| `seed_important_days.py` | 一次性预置生日/纪念日/考试/观演日/重要日五类 fixture |
| `main.py` | 入口：零依赖 Web 后端（**只绑 127.0.0.1**）+ 场景注册表 + 自动开浏览器 |
| `web/` | 前端**构建产物**（`index.html` + `assets/`）：场景目录 + 工作台 + 实时画面，深浅双主题 |
| `web-src/` | 前端源码：Vue 3 + TypeScript + SCSS + Vite；改前端只改这里，再 `npm run build` |
| `assets/app.ico` | 应用图标（9 个尺寸，16~256），`build_exe.py` 打包时自动带走 |
| `assets/icon-source.jpg` | 图标源图：库洛米插画 |
| `tools/make_icon.py` | 由源图重新生成 `app.ico` / `app.png`（`python tools/make_icon.py`） |
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

- **卡片确认前先回桌面首页**：所有场景在截图确认卡片之前都会把界面拉回
  桌面首页（有「智慧建议」卡片区的那一页），判定依据是首页专属控件
  `tc_time` / `tc_date` / `tv_temperature` / 文本「智慧建议」，详见上文
- **未出卡重试会清 launcher3**：点「未出卡，重试」时除清理 atomicbrain /
  atomiccore，还会 `pm clear com.transsion.launcher3`，桌面会短暂重启
- **时间管理三个场景先断网**：`wake_alarm_delay` / `alarm_early_prompt` /
  `alarm_early_close` 第一步会关掉 Wi-Fi 和数据，跑完（含异常）自动恢复
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
- **事件名由程序自动生成**（`gen_name()`），前端不再提供姓名输入框；
  生成的都是 ASCII，因为 `input text` 不支持中文（中文需装 ADBKeyboard）
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
