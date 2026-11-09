import { state } from "@/stores/core";
import type { Scenario } from "@/types/api";

/** 设备前置条件门禁：某些卡片要求设备满足特定条件，不满足时「一键运行」置灰。
 *
 *  目前两条：
 *    * **OOBE 国家=中国** —— 节日祝福卡片（festival_*）；
 *    * **设备已 root** —— 停电建议三张卡（要发 START_TCE_SERVICE 保护的 action）。
 *
 *  为什么做成「置灰」而不是跑到一半再报错
 *  ------------------------------------
 *  以前节日场景跑到一半会弹「是否已在 OOBE 里把国家调整到中国？」让人点；
 *  停电卡则是在 `_check_root()` 里抛错中止。两者都要先白等一两分钟才发现
 *  条件不满足。而这些条件后端一查就知道（`/api/status` 的 country / root），
 *  所以改成开跑前检测、按钮置灰并写明原因，用户点不动也就不会误跑。
 *
 *  判据读不到（null）时**一律放行** —— 宁可放行也别误拦。
 */

/** 依赖中国 OOBE 的场景前缀。 */
const CN_REQUIRED_PREFIX = "festival_";

/** 依赖 root 的场景 id：停电建议三张卡要向 TceService 发 action，
 *  该服务受 signature|privileged 的 START_TCE_SERVICE 保护。 */
const ROOT_REQUIRED_IDS = new Set([
  "power_outage_warning",
  "power_outage_saving",
  "power_outage_restore",
]);

/** 依赖「非 NOTE 系列」的场景 id：纪念日策划案卡在 NOTE 系列上实测不出卡。
 *
 *  为什么改成实时检测而不是写死 `unsupported_note`：
 *  这台设备是 X6766（NOTE 系列）确实跑不出卡，但同一份代码拿到其它机型上
 *  应该能正常跑。写死会把所有机型都拦掉，所以改成按 `/api/status` 的
 *  `modelInfo.is_note` 实时判断。 */
const NON_NOTE_REQUIRED_IDS = new Set(["anniversary"]);

/** 这个场景为什么不能跑；能跑返回 null。
 *
 *  返回的是**完整说明文案**，前端直接拿来做按钮 title 和卡面小字。 */
export function oobeBlockReason(sc: Scenario | null | undefined): string | null {
  if (!sc) return null;

  // ── 纪念日策划案：NOTE 系列不支持 ────────────────────────────
  if (NON_NOTE_REQUIRED_IDS.has(sc.id)) {
    const mi = state.modelInfo;
    if (mi && mi.is_note === true) {
      const which = mi.note_match ? `（${mi.note_match}）` : "";
      return `NOTE 系列手机不支持：纪念日策划案卡片在这类机型上不出卡${which}。`
        + `换一台非 NOTE 系列设备即可正常触发。`;
    }
  }

  // ── 停电建议：必须 root ──────────────────────────────────────
  if (ROOT_REQUIRED_IDS.has(sc.id)) {
    const rt = state.root;
    if (rt && rt.is_root === false) {
      return "设备未 root：停电建议卡片需要向 TceService 注入事件"
        + "（START_TCE_SERVICE 受 signature|privileged 保护，普通 shell 会被拒），"
        + "请换 userdebug/eng 版机型或先执行 adb root。";
    }
  }

  // ── 节日祝福：必须 OOBE 国家=中国 ────────────────────────────
  if (sc.id.startsWith(CN_REQUIRED_PREFIX)) {
    const cn = state.country;
    if (cn && cn.is_cn === false) {
      const where = cn.country ? `（当前 ${cn.country}）` : "";
      return `OOBE 未选择中国：节日祝福卡片需要设备国家为中国才能触发${where}。`
        + `请先在手机 OOBE 里把国家调整到中国。`;
    }
  }

  return null;
}

/** 按钮上显示的**短文案**（完整原因放 title / toast）。 */
export function oobeBlockLabel(sc: Scenario | null | undefined): string {
  const why = oobeBlockReason(sc);
  if (!why) return "";
  if (NON_NOTE_REQUIRED_IDS.has(sc!.id)) return "NOTE 系列不支持";
  return ROOT_REQUIRED_IDS.has(sc!.id) ? "需要 root 设备" : "OOBE 未选择中国";
}

/** 设备整体是否处于「节日卡片不可用」状态（用于顶栏提示）。 */
export function countryBlocksFestivals(): boolean {
  return state.country?.is_cn === false;
}

/** 国家检测结果的简短文案，给顶栏/提示用。 */
export function countryLabel(): string {
  const cn = state.country;
  if (!cn || !cn.country) return "国家未知";
  if (cn.is_cn === true) return "中国";
  if (cn.is_cn === false) return `非中国 · ${cn.country}`;
  return cn.country;
}

/** root 检测结果的简短文案，给顶栏/提示用。 */
export function rootLabel(): string {
  const rt = state.root;
  if (!rt || rt.is_root === null) return "未知";
  return rt.is_root ? "已 root" : "未 root";
}

