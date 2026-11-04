import { api } from "@/lib/api";
import { shortSerial } from "@/lib/format";
import { state } from "@/stores/core";
import type { DeviceEntry } from "@/types/api";
import { appendLine } from "./session";
import { toast } from "./toast";
import { shotStateRefresh, fetchShot } from "./shot";

/** 设备状态轮询 + 多机切换 + 首次抓帧。 */

let lastConnected: boolean | null = null;
let firstShotTried = false;
let timer: number | null = null;

export const deviceConnected = (): boolean | null => lastConnected;

export async function refreshStatus(): Promise<void> {
  try {
    const s = await api.status();
    const conn = Boolean(s.connected);
    state.connected = conn;

    if (conn) {
      state.devTone = "on";
      /* 顶栏胶囊只显示机型，串号放 tooltip（用户要求：别把手机编码摆在界面上） */
      const model = (s.model || "").trim() || "Android";
      const label = model + (s.keyguard ? " · 锁屏中" : "");
      state.devLabel = label;
      state.devTitle = `${model}${s.serial ? ` · ${s.serial}` : ""}\n点击立即重新检测设备`;
      state.devAria = `${label}，已连接。点击重新检测设备`;
      state.devMeta = `${s.width || "?"} × ${s.height || "?"} · ${s.keyguard ? "锁屏" : "亮屏"}`;
    } else {
      state.devTone = "off";
      const label = s.serial ? `设备异常 · ${s.serial}` : "未连接设备";
      state.devLabel = label;
      state.devTitle = s.error || "点击重新检测设备";
      state.devAria = `${label}。点击重新检测设备`;
      state.devMeta = "等待设备接入…";
    }

    if (lastConnected !== null && lastConnected !== conn) {
      toast(conn ? "已自动连接设备" : s.error || "设备断开，自动重连中…", !conn);
    }
    lastConnected = conn;

    state.scrcpyPath = s.scrcpy || "";
    state.scrcpyDisabled = !s.scrcpy;
    state.devices = (s.devices || []).filter((d) => d.state === "device");
    state.selectedSerial = s.selected ?? null;

    shotStateRefresh();

    /* 设备刚连上时主动抓一帧，别让右侧空等自动刷新 */
    if (conn && !firstShotTried && !state.running && !state.starting && !state.hasShot) {
      firstShotTried = true;
      window.setTimeout(() => {
        if (state.connected === true && !state.running && !state.starting) {
          void fetchShot("初始画面 " + new Date().toLocaleTimeString());
        }
      }, 420);
    }
  } catch {
    state.connected = false;
    state.devTone = "off";
    state.devLabel = "服务无响应";
    state.devAria = "本地服务无响应。点击重新检测设备";
    state.devMeta = "本地服务无响应";
    if (lastConnected !== false) {
      toast("服务无响应，正在重试…", true);
      lastConnected = false;
    }
    state.scrcpyDisabled = true;
    state.devices = [];
    shotStateRefresh();
  }
}

/** 点击设备徽标：清掉「上次连接状态」再重测，这样状态没变也会给个 toast */
export function recheckDevice(): void {
  lastConnected = null;
  toast("正在重新检测设备…");
  void refreshStatus();
}

export async function pickDevice(serial: string): Promise<void> {
  try {
    const r = await api.pickDevice(serial);
    if (r.error) {
      toast("选择设备失败：" + r.error, true);
      return;
    }
    state.selectedSerial = serial;
    const dev = state.devices.find((d) => d.serial === serial);
    appendLine("detail", `切换到设备 ${dev ? deviceLabel(dev) : shortSerial(serial)}`);
    void refreshStatus();
  } catch {
    toast("选择设备失败：本地服务无响应", true);
  }
}

export async function launchScrcpy(): Promise<void> {
  try {
    const r = await api.scrcpy();
    if (r.error) toast(r.error, true);
    else toast("已启动 scrcpy");
  } catch {
    toast("启动 scrcpy 失败：本地服务无响应", true);
  }
}

/** 设备状态轮询：连上时 5 秒一次，断开时 3 秒一次（尽快发现插上） */
export function statusSchedule(): void {
  if (timer !== null) clearTimeout(timer);
  timer = window.setTimeout(async () => {
    if (!document.hidden) await refreshStatus();
    statusSchedule();
  }, lastConnected ? 5000 : 3000);
}

/** 设备徽标文字：优先显示机型名（如 X6765），拿不到再退回串号缩写。
 *  串号是内部编号，界面上给用户看机型更直观。 */
export function deviceLabel(d: DeviceEntry): string {
  return (d.model || "").trim() || shortSerial(d.serial);
}
